"""
Singleton HTTP клиент для эмбеддингов с кэшированием.

Переиспользует соединения и кэширует результаты для ускорения.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmbedCache:
    """Простой TTL-кэш для эмбеддингов."""

    def __init__(self, max_size: int = 256, ttl_seconds: float = 300.0) -> None:
        self._cache: OrderedDict[str, tuple[list[list[float]], float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    def _make_key(self, texts: list[str]) -> str:
        normalized = "|".join(t.strip().lower() for t in texts)
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()

    async def get(self, texts: list[str]) -> list[list[float]] | None:
        key = self._make_key(texts)
        async with self._lock:
            if key not in self._cache:
                return None
            embeddings, ts = self._cache[key]
            if time.time() - ts > self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return embeddings

    async def set(self, texts: list[str], embeddings: list[list[float]]) -> None:
        key = self._make_key(texts)
        async with self._lock:
            self._cache[key] = (embeddings, time.time())
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)


class EmbedClient:
    """Singleton клиент для эмбеддинг-сервиса с кэшированием."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        cache_size: int = 256,
        cache_ttl: float = 300.0,
    ) -> None:
        settings = get_settings()
        self._base_url = base_url or str(settings.embed_url)
        self._timeout = timeout or settings.embed_timeout

        http_timeout = httpx.Timeout(
            connect=2.0,
            read=self._timeout,
            write=self._timeout,
            pool=self._timeout,
        )
        self._client = httpx.AsyncClient(timeout=http_timeout)
        self._cache = EmbedCache(max_size=cache_size, ttl_seconds=cache_ttl)

    async def close(self) -> None:
        await self._client.aclose()

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], str | None, int]:
        """
        Возвращает (embeddings, error, latency_ms).
        Использует кэш для повторных запросов.
        """
        if not texts:
            return [], None, 0

        cached = await self._cache.get(texts)
        if cached is not None:
            logger.debug("Embed cache hit for %d texts", len(texts))
            return cached, None, 0

        started = time.perf_counter()

        try:
            response = await self._client.post(self._base_url, json={"texts": list(texts)})
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.error("Embedding request failed: %s", exc, extra={"embed_error": str(exc)})
            return [], str(exc), latency_ms
        except ValueError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.error("Failed to parse embedding response: %s", exc, extra={"embed_error": str(exc)})
            return [], str(exc), latency_ms

        latency_ms = int((time.perf_counter() - started) * 1000)

        embeddings, error = self._parse_response(data)
        if error:
            return [], error, latency_ms

        if embeddings:
            await self._cache.set(texts, embeddings)

        return embeddings, None, latency_ms

    def _parse_response(self, data: Any) -> tuple[list[list[float]], str | None]:
        embeddings: list[list[float]] = []
        expected_dim: int | None = None

        if isinstance(data, dict):
            dim = data.get("dim")
            if isinstance(dim, int) and dim > 0:
                expected_dim = dim

            vectors = data.get("vectors")
            if isinstance(vectors, list):
                for item in vectors:
                    vector = self._normalize_vector(item)
                    if vector:
                        embeddings.append(vector)

        if not embeddings:
            embeddings = self._extract_embeddings(data)

        if expected_dim and embeddings:
            if any(len(vec) != expected_dim for vec in embeddings):
                logger.warning("Embedding dimension mismatch")
                return [], "dim_mismatch"
            if expected_dim != 768:
                logger.warning("Unexpected embedding dimension: %d", expected_dim)
                return [], "unexpected_dim"

        if not embeddings:
            logger.warning("Embedding service returned empty embeddings")
            return [], "empty_embeddings"

        return embeddings, None

    @staticmethod
    def _normalize_vector(vector: Any) -> list[float]:
        if isinstance(vector, list):
            floats = [float(x) for x in vector if isinstance(x, (int, float))]
            if floats:
                return floats
        return []

    def _extract_embeddings(self, data: Any) -> list[list[float]]:
        embeddings: list[list[float]] = []

        if isinstance(data, dict):
            for key in ("embeddings", "vectors", "data", "result"):
                value = data.get(key)
                if isinstance(value, list):
                    embeddings.extend(self._extract_embeddings(value))
            for key in ("embedding", "vector"):
                vector = self._normalize_vector(data.get(key))
                if vector:
                    embeddings.append(vector)
            return embeddings

        if isinstance(data, list):
            if data and all(isinstance(x, (int, float)) for x in data):
                vector = self._normalize_vector(data)
                if vector:
                    embeddings.append(vector)
                return embeddings

            for item in data:
                if isinstance(item, dict):
                    for key in ("embedding", "vector"):
                        vector = self._normalize_vector(item.get(key))
                        if vector:
                            embeddings.append(vector)
                    continue
                vector = self._normalize_vector(item)
                if vector:
                    embeddings.append(vector)

        return embeddings


_CLIENT: EmbedClient | None = None


def get_embed_client() -> EmbedClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = EmbedClient()
    return _CLIENT


async def close_embed_client() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.close()
        _CLIENT = None


__all__ = ["EmbedClient", "EmbedCache", "get_embed_client", "close_embed_client"]

