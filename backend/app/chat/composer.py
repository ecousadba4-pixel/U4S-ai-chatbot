from typing import Any

import asyncpg

from app.booking.service import BookingQuoteService
from app.booking.slot_filling import SlotFiller, SlotState
from app.core.config import get_settings
from app.db.queries.faq import search_faq
from app.llm.amvera_client import AmveraLLMClient
from app.llm.prompts import FACTS_PROMPT
from app.rag.context_builder import build_context
from app.rag.qdrant_client import QdrantClient
from app.rag.retriever import retrieve_context


class ConversationStateStore:
    def get(self, session_id: str) -> SlotState | None:
        raise NotImplementedError

    def set(self, session_id: str, state: SlotState) -> None:
        raise NotImplementedError

    def clear(self, session_id: str) -> None:
        raise NotImplementedError


class InMemoryConversationStateStore(ConversationStateStore):
    def __init__(self) -> None:
        self._storage: dict[str, SlotState] = {}

    def get(self, session_id: str) -> SlotState | None:
        return self._storage.get(session_id)

    def set(self, session_id: str, state: SlotState) -> None:
        self._storage[session_id] = state

    def clear(self, session_id: str) -> None:
        self._storage.pop(session_id, None)


class ChatComposer:
    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        qdrant: QdrantClient,
        llm: AmveraLLMClient,
        slot_filler: SlotFiller,
        booking_service: BookingQuoteService,
        store: ConversationStateStore,
    ) -> None:
        self._pool = pool
        self._qdrant = qdrant
        self._llm = llm
        self._slot_filler = slot_filler
        self._booking_service = booking_service
        self._store = store

    async def handle_booking(self, session_id: str, text: str) -> dict[str, Any]:
        state = self._store.get(session_id) or SlotState()
        state = self._slot_filler.extract(text, state)
        clarification = self._slot_filler.clarification(state)
        self._store.set(session_id, state)

        if clarification:
            question = clarification
            return {
                "answer": question,
                "debug": {
                    "intent": "booking_quote",
                    "slots": state.as_dict(),
                    "pms_called": False,
                    "offers_count": 0,
                },
            }

        guests = state.guests()
        if not guests:
            return {
                "answer": "Не удалось распознать параметры бронирования. Уточните даты и количество гостей.",
                "debug": {
                    "intent": "booking_quote",
                    "slots": state.as_dict(),
                    "pms_called": False,
                    "offers_count": 0,
                },
            }

        offers = await self._booking_service.get_quotes(
            check_in=state.check_in or "",
            check_out=state.check_out or "",
            guests=guests,
        )
        self._store.clear(session_id)

        if not offers:
            return {
                "answer": "К сожалению, нет доступных вариантов на указанные даты.",
                "debug": {
                    "intent": "booking_quote",
                    "slots": state.as_dict(),
                    "pms_called": True,
                    "offers_count": 0,
                },
            }

        summary_lines = []
        for offer in offers:
            line = f"{offer.room_name}: {offer.total_price:.0f} {offer.currency}"
            if offer.breakfast_included:
                line += " (завтрак включён)"
            if offer.room_area:
                line += f", площадь {offer.room_area} м²"
            summary_lines.append(line)
        summary_lines.append("Оформить бронирование?")

        answer = "\n".join(summary_lines)
        return {
            "answer": answer,
            "debug": {
                "intent": "booking_quote",
                "slots": state.as_dict(),
                "pms_called": True,
                "offers_count": len(offers),
            },
        }

    async def handle_general(self, text: str) -> dict[str, Any]:
        settings = get_settings()
        faq_hits = await search_faq(self._pool, query=text, limit=3, min_similarity=0.35)

        rag_hits = await retrieve_context(query=text, client=self._qdrant)
        context_text = build_context(
            facts_hits=rag_hits.get("facts_hits", []),
            files_hits=rag_hits.get("files_hits", []),
            faq_hits=faq_hits,
        )

        system_prompt = FACTS_PROMPT
        if context_text:
            system_prompt = f"{FACTS_PROMPT}\n\n{context_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        answer = await self._llm.chat(model=settings.amvera_model, messages=messages)
        return {
            "answer": answer or "Нет данных в базе знаний.",
            "debug": {
                "intent": "general",
                "context_length": len(context_text),
                "facts_hits": len(rag_hits.get("facts_hits", [])),
                "files_hits": len(rag_hits.get("files_hits", [])),
                "faq_hits": len(faq_hits),
                "rag_min_facts": settings.rag_min_facts,
            },
        }


__all__ = [
    "ConversationStateStore",
    "InMemoryConversationStateStore",
    "ChatComposer",
]
