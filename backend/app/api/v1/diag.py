from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import verify_api_key
from app.core.circuit_breaker import get_circuit_breaker_registry
from app.llm.cache import get_llm_cache
from app.rag.qdrant_client import QdrantClient, get_qdrant_client
from app.rag.retriever import embed_query, qdrant_search
from app.session import SessionStore, get_session_store

router = APIRouter(prefix="/diag", dependencies=[Depends(verify_api_key)])


class QdrantSample(BaseModel):
    scroll_samples: list[dict[str, Any]]
    search_samples: list[dict[str, Any]]


class RedisStatus(BaseModel):
    ok: bool


@router.get("/qdrant_sample", response_model=QdrantSample)
async def qdrant_sample(
    q: str = Query("варианты размещения", description="Тестовый запрос"),
    limit: int = Query(3, ge=1, le=10),
    qdrant: QdrantClient = Depends(get_qdrant_client),
) -> QdrantSample:
    settings = get_settings()

    scroll_hits = await qdrant.scroll(collection=settings.qdrant_collection, limit=limit)
    scroll_samples = []
    for item in scroll_hits:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else None
        if payload is not None:
            scroll_samples.append(payload)
        if len(scroll_samples) >= limit:
            break

    vector = await embed_query(q)
    search_samples: list[dict[str, Any]] = []
    if vector:
        hits = await qdrant_search(
            vector, client=qdrant, limit=limit, collection=settings.qdrant_collection
        )
        for hit in hits[:limit]:
            if not isinstance(hit, dict):
                continue
            search_samples.append(
                {
                    "score": hit.get("score"),
                    "payload": hit.get("payload"),
                }
            )

    return QdrantSample(scroll_samples=scroll_samples, search_samples=search_samples)


@router.get("/redis", response_model=RedisStatus)
async def redis_status(session_store: SessionStore = Depends(get_session_store)) -> RedisStatus:
    ok = await session_store.ping()
    return RedisStatus(ok=ok)


class CircuitBreakerStatus(BaseModel):
    """Статус circuit breaker."""
    breakers: dict[str, dict[str, Any]]


class LLMCacheStatus(BaseModel):
    """Статус LLM кэша."""
    size: int
    max_size: int
    hits: int
    misses: int
    hit_rate_percent: float
    ttl_seconds: float


class HealthStatus(BaseModel):
    """Общий статус системы."""
    status: str
    components: dict[str, bool]
    circuit_breakers: dict[str, str]


@router.get("/circuit_breakers", response_model=CircuitBreakerStatus)
async def circuit_breakers_status() -> CircuitBreakerStatus:
    """Возвращает статус всех circuit breakers."""
    registry = get_circuit_breaker_registry()
    return CircuitBreakerStatus(breakers=registry.get_all_status())


@router.post("/circuit_breakers/reset")
async def reset_circuit_breakers() -> dict[str, str]:
    """Сбрасывает все circuit breakers в CLOSED состояние."""
    registry = get_circuit_breaker_registry()
    await registry.reset_all()
    return {"status": "ok", "message": "All circuit breakers reset to CLOSED"}


@router.get("/llm_cache", response_model=LLMCacheStatus)
async def llm_cache_status() -> LLMCacheStatus:
    """Возвращает статистику LLM кэша."""
    cache = get_llm_cache()
    stats = cache.stats()
    return LLMCacheStatus(**stats)


@router.post("/llm_cache/clear")
async def clear_llm_cache() -> dict[str, Any]:
    """Очищает LLM кэш."""
    cache = get_llm_cache()
    count = await cache.clear()
    return {"status": "ok", "cleared_entries": count}


@router.get("/health", response_model=HealthStatus)
async def health_check(
    qdrant: QdrantClient = Depends(get_qdrant_client),
    session_store: SessionStore = Depends(get_session_store),
) -> HealthStatus:
    """Проверка состояния всех компонентов системы."""
    settings = get_settings()
    
    components: dict[str, bool] = {}
    
    # Проверка Redis
    try:
        components["redis"] = await session_store.ping()
    except Exception:
        components["redis"] = False
    
    # Проверка Qdrant
    try:
        result = await qdrant.scroll(collection=settings.qdrant_collection, limit=1)
        components["qdrant"] = isinstance(result, list)
    except Exception:
        components["qdrant"] = False
    
    # Проверка Embed service
    try:
        from app.rag.embed_client import get_embed_client
        embed_client = get_embed_client()
        embeddings, error, _ = await embed_client.embed(["health check"])
        components["embed"] = bool(embeddings) and not error
    except Exception:
        components["embed"] = False
    
    # Статус circuit breakers
    registry = get_circuit_breaker_registry()
    cb_status = {name: status["state"] for name, status in registry.get_all_status().items()}
    
    # Общий статус: healthy если все критические компоненты работают
    all_healthy = all(components.get(c, False) for c in ["qdrant", "embed"])
    status = "healthy" if all_healthy else "degraded"
    
    return HealthStatus(
        status=status,
        components=components,
        circuit_breakers=cb_status,
    )


__all__ = ["router"]
