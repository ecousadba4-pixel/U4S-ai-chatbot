from __future__ import annotations

import logging

from fastapi import Depends, FastAPI

from app.api.v1 import admin, chat, diag, facts, knowledge, rag_search
from app.booking.service import BookingQuoteService
from app.booking.shelter_client import ShelterCloudService
from app.booking.slot_filling import SlotFiller
from app.chat.composer import ChatComposer, InMemoryConversationStateStore
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.pool import get_pool
from app.llm.amvera_client import AmveraLLMClient
from app.rag.embed_client import close_embed_client, get_embed_client
from app.rag.qdrant_client import QdrantClient, get_qdrant_client

logger = logging.getLogger(__name__)

settings = get_settings()
setup_logging()

state_store = InMemoryConversationStateStore()
booking_state_store = InMemoryConversationStateStore()
slot_filler = SlotFiller()
qdrant_client = get_qdrant_client()
llm_client = AmveraLLMClient()
shelter_service = ShelterCloudService()
booking_service = BookingQuoteService(shelter_service)


async def _warmup_connections() -> None:
    """Прогрев соединений при старте для устранения холодного старта."""
    logger.info("Warming up connections...")

    # Прогрев embed клиента
    embed_client = get_embed_client()
    try:
        await embed_client.embed(["warmup"])
        logger.info("Embed client warmed up")
    except Exception as exc:
        logger.warning("Embed warmup failed: %s", exc)

    # Прогрев Qdrant клиента
    try:
        await qdrant_client.scroll(collection=settings.qdrant_collection, limit=1)
        logger.info("Qdrant client warmed up")
    except Exception as exc:
        logger.warning("Qdrant warmup failed: %s", exc)

    logger.info("Warmup complete")


async def lifespan(app: FastAPI):
    pool = await get_pool()

    # Прогрев соединений
    await _warmup_connections()

    try:
        yield
    finally:
        await pool.close()
        await qdrant_client.close()
        await llm_client.close()
        await shelter_service.close()
        await close_embed_client()


def composer_dependency(pool=Depends(get_pool)) -> ChatComposer:
    return ChatComposer(
        pool=pool,
        qdrant=qdrant_client,
        llm=llm_client,
        slot_filler=slot_filler,
        booking_service=booking_service,
        store=state_store,
        booking_fsm_store=booking_state_store,
        settings=settings,
    )


def create_app() -> FastAPI:
    app = FastAPI(title="U4S Chat API", lifespan=lifespan)
    api_prefix = settings.api_prefix

    app.dependency_overrides[chat.get_composer] = composer_dependency

    app.include_router(chat.router, prefix=api_prefix)
    app.include_router(facts.router, prefix=api_prefix)
    app.include_router(knowledge.router, prefix=api_prefix)
    app.include_router(rag_search.router, prefix=api_prefix)
    app.include_router(diag.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)
    return app


app = create_app()
