"""
Семантический кэш для LLM ответов.

Кэширует ответы на основе нормализованного вопроса, intent и контекста.
Позволяет быстро отдавать повторные ответы без вызова LLM.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)


class LLMCache:
    """
    Семантический кэш для LLM ответов.
    
    Ключ кэша формируется из:
    - Нормализованного текста вопроса (lowercase, stripped)
    - Intent запроса
    - Хэша первых N символов контекста (для учёта RAG данных)
    """

    def __init__(
        self,
        max_size: int = 512,
        ttl_seconds: float = 600.0,
        context_hash_length: int = 500,
    ) -> None:
        self._cache: OrderedDict[str, tuple[str, float, dict[str, Any]]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._context_hash_length = context_hash_length
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    def _normalize_query(self, query: str) -> str:
        """Нормализует запрос для кэширования."""
        normalized = query.strip().lower()
        # Убираем множественные пробелы
        normalized = " ".join(normalized.split())
        return normalized

    def _make_key(self, query: str, intent: str, context: str) -> str:
        """Создаёт ключ кэша."""
        normalized_query = self._normalize_query(query)
        context_snippet = context[:self._context_hash_length] if context else ""
        context_hash = hashlib.md5(
            context_snippet.encode(), usedforsecurity=False
        ).hexdigest()[:12]
        
        key_string = f"{normalized_query}|{intent}|{context_hash}"
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    async def get(
        self,
        query: str,
        intent: str,
        context: str = "",
    ) -> tuple[str | None, dict[str, Any] | None]:
        """
        Получает кэшированный ответ.
        
        Returns:
            Tuple из (answer, debug_info) или (None, None) если не найдено
        """
        key = self._make_key(query, intent, context)
        
        async with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None, None
            
            answer, ts, debug_info = self._cache[key]
            if time.time() - ts > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None, None
            
            # Обновляем позицию (LRU)
            self._cache.move_to_end(key)
            self._hits += 1
            
            logger.debug(
                "LLM cache hit for query: %s (hits=%d, misses=%d)",
                query[:50], self._hits, self._misses
            )
            
            return answer, debug_info

    async def set(
        self,
        query: str,
        intent: str,
        context: str,
        answer: str,
        debug_info: dict[str, Any] | None = None,
    ) -> None:
        """
        Сохраняет ответ в кэш.
        
        Args:
            query: Исходный вопрос пользователя
            intent: Определённый intent
            context: RAG контекст
            answer: Ответ LLM
            debug_info: Отладочная информация (опционально)
        """
        key = self._make_key(query, intent, context)
        
        async with self._lock:
            self._cache[key] = (answer, time.time(), debug_info or {})
            self._cache.move_to_end(key)
            
            # Удаляем старые записи если превышен лимит
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    async def invalidate(self, query: str, intent: str, context: str = "") -> bool:
        """Удаляет запись из кэша."""
        key = self._make_key(query, intent, context)
        
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self) -> int:
        """Очищает весь кэш. Возвращает количество удалённых записей."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            return count

    def stats(self) -> dict[str, Any]:
        """Возвращает статистику кэша."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_percent": round(hit_rate, 2),
            "ttl_seconds": self._ttl,
        }


# === Singleton ===

_LLM_CACHE: LLMCache | None = None


def get_llm_cache() -> LLMCache:
    """Возвращает singleton экземпляр LLM кэша."""
    global _LLM_CACHE
    if _LLM_CACHE is None:
        from app.core.config import get_settings
        settings = get_settings()
        _LLM_CACHE = LLMCache(
            max_size=512,
            ttl_seconds=settings.llm_cache_ttl,
        )
    return _LLM_CACHE


def reset_llm_cache() -> None:
    """Сбрасывает singleton для тестов."""
    global _LLM_CACHE
    _LLM_CACHE = None


__all__ = ["LLMCache", "get_llm_cache", "reset_llm_cache"]

