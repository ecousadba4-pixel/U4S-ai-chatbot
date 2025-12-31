"""
Модуль ядра приложения.

Содержит:
- Конфигурацию приложения (Settings)
- Feature flags сервис
- Circuit breaker
- Логирование
- Безопасность (API keys)
"""

from app.core.config import Settings, get_settings
from app.core.feature_flags import (
    FeatureFlagsService,
    FeatureFlagStatus,
    get_feature_flags_service,
)

__all__ = [
    "Settings",
    "get_settings",
    "FeatureFlagsService",
    "FeatureFlagStatus",
    "get_feature_flags_service",
]
