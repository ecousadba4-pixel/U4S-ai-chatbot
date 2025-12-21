from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация приложения на основе переменных окружения."""

    database_url: str = Field(..., alias="DATABASE_URL")
    qdrant_url: AnyHttpUrl | None = Field(None, alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field("u4s_kb", alias="QDRANT_COLLECTION")
    embed_url: AnyHttpUrl = Field(..., alias="EMBED_URL")
    rag_facts_limit: int = Field(5, alias="RAG_FACTS_LIMIT")
    rag_files_limit: int = Field(3, alias="RAG_FILES_LIMIT")
    rag_max_context_chars: int = Field(2500, alias="RAG_MAX_CONTEXT_CHARS")
    rag_max_snippets: int = Field(5, alias="RAG_MAX_SNIPPETS")
    rag_min_facts: int = Field(3, alias="RAG_MIN_FACTS")
    rag_score_threshold: float = Field(0.2, alias="RAG_SCORE_THRESHOLD")
    redis_url: str = Field("redis://127.0.0.1:6379/0", alias="REDIS_URL")
    session_ttl_seconds: int = Field(259_200, alias="SESSION_TTL_SECONDS")
    amvera_api_token: str = Field(..., alias="AMVERA_API_TOKEN")
    amvera_api_url: AnyHttpUrl = Field(
        "https://llm.amvera.ai", alias="AMVERA_API_URL"
    )
    amvera_inference_name: str = Field("deepseek", alias="AMVERA_INFERENCE_NAME")
    amvera_model: str = Field("deepseek-chat", alias="AMVERA_MODEL")
    shelter_cloud_token: str = Field(..., alias="SHELTER_CLOUD_TOKEN")

    llm_dry_run: bool = Field(False, alias="LLM_DRY_RUN")
    llm_temperature: float = Field(0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(350, alias="LLM_MAX_TOKENS")
    llm_timeout: float = Field(20.0, alias="LLM_TIMEOUT")

    max_options: int = Field(6, alias="MAX_OPTIONS")

    app_env: Literal["dev", "prod", "test"] = Field("dev", alias="APP_ENV")
    api_prefix: str = "/v1"

    include_debug: bool = Field(
        False,
        alias="INCLUDE_DEBUG",
        description="Управляет добавлением отладочной информации в ответы API",
    )

    request_timeout: float = 30.0
    completion_timeout: float = Field(60.0, alias="COMPLETION_TIMEOUT")
    embed_timeout: float = Field(5.0, alias="EMBED_TIMEOUT")

    # === Новые настройки для оптимизации ===
    
    # История диалога
    conversation_history_limit: int = Field(
        10, 
        alias="CONVERSATION_HISTORY_LIMIT",
        description="Максимальное количество сообщений в истории диалога для LLM"
    )
    
    # Circuit breaker
    circuit_breaker_threshold: int = Field(
        5, 
        alias="CIRCUIT_BREAKER_THRESHOLD",
        description="Количество ошибок для открытия circuit breaker"
    )
    circuit_breaker_timeout: float = Field(
        30.0, 
        alias="CIRCUIT_BREAKER_TIMEOUT",
        description="Время ожидания перед попыткой восстановления (секунды)"
    )
    
    # LLM кэш
    llm_cache_enabled: bool = Field(
        True, 
        alias="LLM_CACHE_ENABLED",
        description="Включить кэширование LLM ответов"
    )
    llm_cache_ttl: float = Field(
        600.0, 
        alias="LLM_CACHE_TTL",
        description="TTL кэша LLM ответов в секундах (по умолчанию 10 минут)"
    )
    
    # Streaming
    llm_streaming_enabled: bool = Field(
        False, 
        alias="LLM_STREAMING_ENABLED",
        description="Включить streaming режим для LLM (быстрый первый токен)"
    )

    # Shared caches (RAG/LLM)
    use_redis_cache: bool = Field(
        True,
        alias="USE_REDIS_CACHE",
        description="Использовать Redis для кэшей RAG и LLM",
    )
    rag_cache_ttl: float = Field(
        120.0,
        alias="RAG_CACHE_TTL",
        description="TTL RAG-кэша в секундах",
    )
    
    # Redis state store
    use_redis_state_store: bool = Field(
        True,
        alias="USE_REDIS_STATE_STORE",
        description="Использовать Redis для хранения состояния диалога (вместо in-memory)"
    )

    # Startup warmup
    enable_startup_warmup: bool = Field(
        True,
        alias="ENABLE_STARTUP_WARMUP",
        description="Выполнять прогрев внешних сервисов при старте",
    )

    @model_validator(mode="after")
    def _resolve_qdrant_config(self) -> "Settings":
        """Обработка fallback для Qdrant URL и API key."""
        # Fallback для Qdrant URL
        if not self.qdrant_url:
            for env_var in ["QDRANT_HTTP_URL", "QDRANT_ENDPOINT"]:
                value = os.getenv(env_var)
                if value:
                    self.qdrant_url = AnyHttpUrl(value)
                    break
            if not self.qdrant_url:
                raise ValueError("QDRANT_URL, QDRANT_HTTP_URL or QDRANT_ENDPOINT must be set")
        
        # Fallback для Qdrant API key
        if not self.qdrant_api_key:
            for env_var in ["QDRANT_SERVICE_API_KEY", "QDRANT__SERVICE__API_KEY", "QDRANT_APIKEY"]:
                value = os.getenv(env_var)
                if value:
                    self.qdrant_api_key = value
                    break
        
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
