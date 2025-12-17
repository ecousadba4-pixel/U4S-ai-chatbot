"""
Circuit Breaker для защиты от каскадных сбоев внешних сервисов.

Предотвращает перегрузку системы при недоступности LLM, Embedding
или других внешних сервисов.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Состояния circuit breaker."""
    CLOSED = "closed"       # Нормальная работа, запросы проходят
    OPEN = "open"           # Сервис недоступен, запросы блокируются
    HALF_OPEN = "half_open"  # Пробный режим, проверяем восстановление


@dataclass
class CircuitBreakerConfig:
    """Конфигурация circuit breaker."""
    failure_threshold: int = 5       # Количество ошибок для открытия
    recovery_timeout: float = 30.0   # Секунд до перехода в HALF_OPEN
    half_open_max_calls: int = 3     # Успешных вызовов для закрытия
    success_threshold: int = 2       # Успешных вызовов в HALF_OPEN для закрытия


@dataclass
class CircuitBreakerStats:
    """Статистика circuit breaker."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Отклонённые в состоянии OPEN
    state_changes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None


class CircuitBreaker:
    """
    Circuit Breaker для защиты от каскадных сбоев.
    
    Пример использования:
    ```python
    breaker = CircuitBreaker("llm_service")
    
    result = await breaker.call(
        llm_client.chat,
        messages=messages,
        fallback="Сервис временно недоступен"
    )
    ```
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._lock = asyncio.Lock()
        self._stats = CircuitBreakerStats()

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        return self._stats

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Callable[..., Awaitable[T]] | T | None = None,
        **kwargs: Any,
    ) -> T:
        """
        Выполняет вызов с защитой circuit breaker.
        
        Args:
            func: Асинхронная функция для вызова
            *args: Позиционные аргументы функции
            fallback: Fallback значение или функция при открытом breaker
            **kwargs: Именованные аргументы функции
            
        Returns:
            Результат вызова или fallback значение
            
        Raises:
            CircuitBreakerOpenError: Если breaker открыт и нет fallback
        """
        self._stats.total_calls += 1

        # Проверяем состояние и возможность перехода
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
                else:
                    self._stats.rejected_calls += 1
                    logger.warning(
                        "Circuit %s is OPEN, rejecting call (rejected=%d)",
                        self._name, self._stats.rejected_calls
                    )
                    return await self._execute_fallback(fallback)

        # Выполняем вызов
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure(exc)
            logger.warning(
                "Circuit %s: call failed: %s (failures=%d/%d)",
                self._name, exc, self._failure_count, self._config.failure_threshold
            )
            return await self._execute_fallback(fallback)

    def _should_attempt_reset(self) -> bool:
        """Проверяет, пора ли пробовать восстановление."""
        if self._last_failure_time == 0:
            return True
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self._config.recovery_timeout

    async def _on_success(self) -> None:
        """Обрабатывает успешный вызов."""
        async with self._lock:
            self._stats.successful_calls += 1
            self._stats.last_success_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                # Сбрасываем счётчик ошибок при успехе
                self._failure_count = 0

    async def _on_failure(self, exc: Exception) -> None:
        """Обрабатывает неудачный вызов."""
        async with self._lock:
            self._stats.failed_calls += 1
            self._stats.last_failure_time = time.time()
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # При ошибке в HALF_OPEN сразу открываем
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self._config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Переход в новое состояние."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1
        
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0
        
        logger.info(
            "Circuit %s: %s -> %s (changes=%d)",
            self._name, old_state.value, new_state.value, self._stats.state_changes
        )

    async def _execute_fallback(
        self,
        fallback: Callable[..., Awaitable[T]] | T | None,
    ) -> T:
        """Выполняет fallback."""
        if fallback is None:
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self._name}' is open and no fallback provided"
            )
        
        if callable(fallback):
            if asyncio.iscoroutinefunction(fallback):
                return await fallback()
            return fallback()  # type: ignore
        
        return fallback

    async def reset(self) -> None:
        """Принудительный сброс в CLOSED состояние."""
        async with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0

    def get_status(self) -> dict[str, Any]:
        """Возвращает текущий статус breaker."""
        return {
            "name": self._name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "config": {
                "failure_threshold": self._config.failure_threshold,
                "recovery_timeout": self._config.recovery_timeout,
                "half_open_max_calls": self._config.half_open_max_calls,
            },
            "stats": {
                "total_calls": self._stats.total_calls,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "rejected_calls": self._stats.rejected_calls,
                "state_changes": self._stats.state_changes,
            },
        }


class CircuitBreakerOpenError(Exception):
    """Исключение при открытом circuit breaker без fallback."""
    pass


# === Registry для управления breakers ===

class CircuitBreakerRegistry:
    """Реестр circuit breakers для централизованного управления."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._default_config = CircuitBreakerConfig()

    def get(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Получает или создаёт circuit breaker по имени."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name, config or self._default_config
            )
        return self._breakers[name]

    def set_default_config(self, config: CircuitBreakerConfig) -> None:
        """Устанавливает конфигурацию по умолчанию."""
        self._default_config = config

    async def reset_all(self) -> None:
        """Сбрасывает все breakers."""
        for breaker in self._breakers.values():
            await breaker.reset()

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Возвращает статус всех breakers."""
        return {name: breaker.get_status() for name, breaker in self._breakers.items()}

    def list_names(self) -> list[str]:
        """Возвращает список имён всех breakers."""
        return list(self._breakers.keys())


# === Singleton ===

_REGISTRY: CircuitBreakerRegistry | None = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Возвращает singleton реестр circuit breakers."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = CircuitBreakerRegistry()
        
        # Настраиваем конфигурацию из settings
        from app.core.config import get_settings
        settings = get_settings()
        _REGISTRY.set_default_config(CircuitBreakerConfig(
            failure_threshold=settings.circuit_breaker_threshold,
            recovery_timeout=settings.circuit_breaker_timeout,
        ))
    
    return _REGISTRY


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Shortcut для получения circuit breaker по имени."""
    return get_circuit_breaker_registry().get(name)


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitBreakerRegistry",
    "CircuitState",
    "get_circuit_breaker",
    "get_circuit_breaker_registry",
]

