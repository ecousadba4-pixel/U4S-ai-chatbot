from __future__ import annotations

from typing import Any, Iterable

import httpx

from app.core.config import get_settings
from app.rag.qdrant_client import QdrantClient


def _extract_embedding(data: Any) -> list[float]:
    if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
        return [float(x) for x in data]

    if isinstance(data, dict):
        for key in ("embedding", "vector"):
            value = data.get(key)
            if isinstance(value, list):
                return [float(x) for x in value if isinstance(x, (int, float))]

        data_field = data.get("data")
        if isinstance(data_field, dict):
            for key in ("embedding", "vector"):
                value = data_field.get(key)
                if isinstance(value, list):
                    return [float(x) for x in value if isinstance(x, (int, float))]
        if isinstance(data_field, list) and data_field:
            first = data_field[0]
            if isinstance(first, dict):
                nested = first.get("embedding") or first.get("vector")
                if isinstance(nested, list):
                    return [float(x) for x in nested if isinstance(x, (int, float))]

    return []


async def embed_query(text: str) -> list[float]:
    """Запрашивает embedding у внешнего сервиса."""

    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        response = await client.post(str(settings.embed_url), json={"text": text})
        response.raise_for_status()
        data = response.json()
    return _extract_embedding(data)


def _build_filter(*, source_prefix: str | None, types: Iterable[str] | None) -> dict[str, Any] | None:
    filters = []
    if source_prefix:
        match_key = "text" if source_prefix.endswith(":") else "value"
        filters.append({"key": "payload.source", "match": {match_key: source_prefix}})
    if types:
        type_list = [item for item in types if item]
        if type_list:
            filters.append({"key": "payload.type", "match": {"any": type_list}})

    if not filters:
        return None
    return {"must": filters}


async def qdrant_search(
    vector: Iterable[float],
    *,
    client: QdrantClient,
    limit: int = 6,
    source_prefix: str | None = None,
    types: Iterable[str] | None = None,
    collection: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    query_filter = _build_filter(source_prefix=source_prefix, types=types)
    return await client.search(
        collection=collection or settings.qdrant_collection,
        vector=vector,
        limit=limit,
        query_filter=query_filter,
    )


def _extract_text(payload: dict[str, Any]) -> str:
    for key in ("text", "content", "chunk", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_hit(hit: dict[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    text = _extract_text(payload)
    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    entity_id = payload.get("entity_id") if isinstance(payload.get("entity_id"), str) else None
    source = payload.get("source") if isinstance(payload.get("source"), str) else None
    type_value = payload.get("type") if isinstance(payload.get("type"), str) else None

    return {
        "score": float(hit.get("score", 0.0) or 0.0),
        "type": type_value,
        "title": title,
        "entity_id": entity_id,
        "text": text,
        "source": source,
        "payload": payload,
    }


def _deduplicate_hits(
    hits: list[dict[str, Any]], *, seen: set[str] | None = None
) -> list[dict[str, Any]]:
    known = seen if seen is not None else set()
    unique: list[dict[str, Any]] = []
    for hit in hits:
        text = hit.get("text") or ""
        title = hit.get("title") or ""
        key = f"{title}::{text[:80]}"
        if key in known:
            continue
        known.add(key)
        unique.append(hit)
    return unique


async def retrieve_context(query: str, *, client: QdrantClient) -> dict[str, list[dict[str, Any]]]:
    settings = get_settings()
    try:
        vector = await embed_query(query)
    except Exception:
        return {"facts_hits": [], "files_hits": []}
    if not vector:
        return {"facts_hits": [], "files_hits": []}

    try:
        facts_raw = await qdrant_search(
            vector,
            client=client,
            limit=settings.rag_facts_limit,
            source_prefix="postgres:u4s_chatbot",
        )
    except Exception:
        facts_raw = []

    dedup_keys: set[str] = set()
    facts_hits = [_normalize_hit(item) for item in facts_raw]
    facts_hits = _deduplicate_hits(facts_hits, seen=dedup_keys)

    files_hits: list[dict[str, Any]] = []
    if len(facts_hits) < settings.rag_min_facts:
        try:
            files_raw = await qdrant_search(
                vector,
                client=client,
                limit=settings.rag_files_limit,
                source_prefix="file:",
            )
        except Exception:
            files_raw = []
        files_hits = _deduplicate_hits([
            _normalize_hit(item) for item in files_raw
        ], seen=dedup_keys)

    return {"facts_hits": facts_hits, "files_hits": files_hits}


async def search_hits_with_payload(
    query: str, *, client: QdrantClient
) -> dict[str, list[dict[str, Any]]]:
    settings = get_settings()
    try:
        vector = await embed_query(query)
    except Exception:
        return {"facts": [], "files": []}
    if not vector:
        return {"facts": [], "files": []}

    try:
        facts_hits = await qdrant_search(
            vector,
            client=client,
            limit=settings.rag_facts_limit,
            source_prefix="postgres:u4s_chatbot",
        )
    except Exception:
        facts_hits = []
    files_hits: list[dict[str, Any]] = []
    if len(facts_hits) < settings.rag_min_facts:
        try:
            files_hits = await qdrant_search(
                vector,
                client=client,
                limit=settings.rag_files_limit,
                source_prefix="file:",
            )
        except Exception:
            files_hits = []

    return {"facts": facts_hits, "files": files_hits}


__all__ = [
    "embed_query",
    "qdrant_search",
    "retrieve_context",
    "search_hits_with_payload",
]
