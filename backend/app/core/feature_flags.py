"""
Централизованный сервис для управления feature flags и их статусами.

Собирает все настройки включения/выключения функций в одном месте
для упрощённой диагностики и управления.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.core.config import get_settings, Settings


@dataclass
class FeatureFlagStatus:
    """Статус одного feature flag."""
    
    name: str
    enabled: bool
    description: str
    category: str
    health_status: str = "unknown"  # "healthy", "degraded", "unavailable", "unknown"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "description": self.description,
            "category": self.category,
            "health_status": self.health_status,
            "details": self.details,
        }


class FeatureFlagsService:
    """
    Сервис для централизованного управления feature flags.
    
    Группы флагов:
    - storage: настройки хранилища состояния (Redis vs in-memory)
    - caching: настройки кэширования (LLM, RAG)
    - resilience: настройки отказоустойчивости (circuit breakers)
    - llm: настройки LLM (streaming, dry-run)
    - startup: настройки запуска (warmup)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def get_all_flags(self) -> list[FeatureFlagStatus]:
        """Возвращает все feature flags с их статусами."""
        return [
            # Storage
            FeatureFlagStatus(
                name="use_redis_state_store",
                enabled=self._settings.use_redis_state_store,
                description="Использовать Redis для хранения состояния диалога",
                category="storage",
            ),
            FeatureFlagStatus(
                name="use_redis_cache",
                enabled=self._settings.use_redis_cache,
                description="Использовать Redis для кэшей RAG и LLM",
                category="caching",
            ),
            # Caching
            FeatureFlagStatus(
                name="llm_cache_enabled",
                enabled=self._settings.llm_cache_enabled,
                description="Кэширование ответов LLM",
                category="caching",
                details={
                    "ttl_seconds": self._settings.llm_cache_ttl,
                },
            ),
            # LLM
            FeatureFlagStatus(
                name="llm_streaming_enabled",
                enabled=self._settings.llm_streaming_enabled,
                description="Streaming режим для LLM (быстрый первый токен)",
                category="llm",
            ),
            FeatureFlagStatus(
                name="llm_dry_run",
                enabled=self._settings.llm_dry_run,
                description="Режим сухого запуска LLM (без реальных запросов)",
                category="llm",
            ),
            # Resilience
            FeatureFlagStatus(
                name="circuit_breaker",
                enabled=True,  # Always enabled, configurable threshold
                description="Circuit breaker для внешних сервисов",
                category="resilience",
                details={
                    "threshold": self._settings.circuit_breaker_threshold,
                    "timeout_seconds": self._settings.circuit_breaker_timeout,
                },
            ),
            # Startup
            FeatureFlagStatus(
                name="enable_startup_warmup",
                enabled=self._settings.enable_startup_warmup,
                description="Прогрев внешних сервисов при старте",
                category="startup",
            ),
        ]

    def get_flags_by_category(self, category: str) -> list[FeatureFlagStatus]:
        """Возвращает feature flags указанной категории."""
        return [flag for flag in self.get_all_flags() if flag.category == category]

    def get_flag(self, name: str) -> FeatureFlagStatus | None:
        """Возвращает конкретный feature flag по имени."""
        for flag in self.get_all_flags():
            if flag.name == name:
                return flag
        return None

    def is_enabled(self, name: str) -> bool:
        """Проверяет, включён ли feature flag."""
        flag = self.get_flag(name)
        return flag.enabled if flag else False

    def get_summary(self) -> dict[str, Any]:
        """Возвращает сводку по всем feature flags."""
        flags = self.get_all_flags()
        by_category: dict[str, list[dict[str, Any]]] = {}
        
        for flag in flags:
            if flag.category not in by_category:
                by_category[flag.category] = []
            by_category[flag.category].append(flag.to_dict())
        
        enabled_count = sum(1 for f in flags if f.enabled)
        
        return {
            "total_flags": len(flags),
            "enabled_count": enabled_count,
            "disabled_count": len(flags) - enabled_count,
            "by_category": by_category,
        }

    async def update_health_status(
        self,
        redis_healthy: bool | None = None,
        qdrant_healthy: bool | None = None,
        embed_healthy: bool | None = None,
    ) -> list[FeatureFlagStatus]:
        """
        Обновляет health status для флагов на основе реального состояния сервисов.
        """
        flags = self.get_all_flags()
        
        for flag in flags:
            if flag.name == "use_redis_state_store":
                if redis_healthy is None:
                    flag.health_status = "unknown"
                elif not flag.enabled:
                    flag.health_status = "disabled"
                elif redis_healthy:
                    flag.health_status = "healthy"
                else:
                    flag.health_status = "degraded"
                    
            elif flag.name == "use_redis_cache":
                if redis_healthy is None:
                    flag.health_status = "unknown"
                elif not flag.enabled:
                    flag.health_status = "disabled"
                elif redis_healthy:
                    flag.health_status = "healthy"
                else:
                    flag.health_status = "degraded"
                    
            elif flag.name == "llm_cache_enabled":
                # LLM cache can work with in-memory even if Redis is down
                if flag.enabled:
                    flag.health_status = "healthy"
                else:
                    flag.health_status = "disabled"
        
        return flags


@lru_cache(maxsize=1)
def get_feature_flags_service() -> FeatureFlagsService:
    """Возвращает singleton экземпляр FeatureFlagsService."""
    return FeatureFlagsService()


__all__ = ["FeatureFlagsService", "FeatureFlagStatus", "get_feature_flags_service"]
