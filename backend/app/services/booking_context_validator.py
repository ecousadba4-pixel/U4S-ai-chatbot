"""
Сервис валидации контекста бронирования.

Централизует повторяющиеся проверки состояния FSM и данных контекста,
убирая дублирование из основного BookingFsmService.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, List, Set

from app.booking.fsm import BookingContext, BookingState

logger = logging.getLogger(__name__)


# Состояния, требующие наличия checkin
STATES_REQUIRING_CHECKIN: Set[BookingState] = frozenset({
    BookingState.ASK_NIGHTS_OR_CHECKOUT,
    BookingState.ASK_ADULTS,
    BookingState.ASK_CHILDREN_COUNT,
    BookingState.ASK_CHILDREN_AGES,
    BookingState.CALCULATE,
})

# Состояния, требующие наличия nights или checkout
STATES_REQUIRING_STAY_DURATION: Set[BookingState] = frozenset({
    BookingState.ASK_ADULTS,
    BookingState.ASK_CHILDREN_COUNT,
    BookingState.ASK_CHILDREN_AGES,
    BookingState.CALCULATE,
})


@dataclass
class ValidationResult:
    """Результат валидации контекста."""
    
    is_valid: bool
    errors: List[str]
    suggested_state: BookingState | None = None
    fields_to_clear: List[str] | None = None

    @classmethod
    def ok(cls) -> "ValidationResult":
        """Создаёт успешный результат валидации."""
        return cls(is_valid=True, errors=[])

    @classmethod
    def error(
        cls,
        errors: List[str],
        suggested_state: BookingState | None = None,
        fields_to_clear: List[str] | None = None,
    ) -> "ValidationResult":
        """Создаёт результат с ошибкой валидации."""
        return cls(
            is_valid=False,
            errors=errors,
            suggested_state=suggested_state,
            fields_to_clear=fields_to_clear,
        )


class BookingContextValidator:
    """Сервис для валидации контекста бронирования."""

    def validate_context_for_state(
        self, context: BookingContext, target_state: BookingState | None = None
    ) -> ValidationResult:
        """
        Валидирует контекст для указанного состояния.
        
        Args:
            context: Контекст бронирования
            target_state: Целевое состояние (если None, используется текущее)
            
        Returns:
            Результат валидации с ошибками и рекомендациями.
        """
        state = target_state or context.state
        if state is None:
            return ValidationResult.ok()
        
        errors: List[str] = []
        
        # Проверка checkin для состояний, которые его требуют
        if state in STATES_REQUIRING_CHECKIN:
            checkin_result = self._validate_checkin(context)
            if not checkin_result.is_valid:
                return checkin_result
        
        # Проверка duration для состояний, которые его требуют
        if state in STATES_REQUIRING_STAY_DURATION:
            duration_result = self._validate_stay_duration(context)
            if not duration_result.is_valid:
                errors.extend(duration_result.errors)
        
        # Специфичные проверки для состояния CALCULATE
        if state == BookingState.CALCULATE:
            calc_result = self._validate_for_calculation(context)
            if not calc_result.is_valid:
                return calc_result
        
        if errors:
            return ValidationResult.error(errors)
        
        return ValidationResult.ok()

    def _validate_checkin(self, context: BookingContext) -> ValidationResult:
        """Валидирует дату заезда (наличие и формат)."""
        if not context.checkin:
            logger.warning(
                "Context validation failed: state %s requires checkin but it's missing. "
                "Context: %s",
                context.state,
                context.compact(),
            )
            return ValidationResult.error(
                errors=["Дата заезда не указана"],
                suggested_state=BookingState.ASK_CHECKIN,
                fields_to_clear=["checkin"],
            )
        
        # Проверка формата даты
        try:
            _checkin_date = date.fromisoformat(context.checkin)
        except ValueError:
            logger.warning(
                "Invalid checkin date format: %s", context.checkin
            )
            return ValidationResult.error(
                errors=["Дата заезда указана неверно"],
                suggested_state=BookingState.ASK_CHECKIN,
                fields_to_clear=["checkin"],
            )
        
        # Примечание: проверка на дату в прошлом выполняется при парсинге,
        # здесь мы только проверяем наличие и формат
        
        return ValidationResult.ok()

    def _validate_stay_duration(self, context: BookingContext) -> ValidationResult:
        """Валидирует продолжительность проживания."""
        if context.nights is not None and context.nights > 0:
            return ValidationResult.ok()
        
        if context.checkout:
            try:
                checkout_date = date.fromisoformat(context.checkout)
                if context.checkin:
                    checkin_date = date.fromisoformat(context.checkin)
                    if checkout_date > checkin_date:
                        return ValidationResult.ok()
                    return ValidationResult.error(
                        errors=["Дата выезда должна быть позже даты заезда"],
                        suggested_state=BookingState.ASK_NIGHTS_OR_CHECKOUT,
                        fields_to_clear=["checkout"],
                    )
            except ValueError:
                return ValidationResult.error(
                    errors=["Дата выезда указана неверно"],
                    suggested_state=BookingState.ASK_NIGHTS_OR_CHECKOUT,
                    fields_to_clear=["checkout"],
                )
        
        # Nights и checkout оба None - это OK для некоторых состояний
        return ValidationResult.ok()

    def _validate_for_calculation(self, context: BookingContext) -> ValidationResult:
        """Валидирует контекст для расчёта бронирования."""
        errors: List[str] = []
        
        if not context.checkin:
            errors.append("Дата заезда не указана")
        
        if context.nights is None and not context.checkout:
            errors.append("Количество ночей или дата выезда не указаны")
        
        if context.adults is None:
            errors.append("Количество взрослых не указано")
        
        if (context.children or 0) > 0 and not context.children_ages:
            errors.append("Возраст детей не указан")
        
        if errors:
            # Определяем, к какому состоянию вернуться
            if not context.checkin:
                suggested = BookingState.ASK_CHECKIN
            elif context.nights is None and not context.checkout:
                suggested = BookingState.ASK_NIGHTS_OR_CHECKOUT
            elif context.adults is None:
                suggested = BookingState.ASK_ADULTS
            else:
                suggested = BookingState.ASK_CHILDREN_AGES
            
            return ValidationResult.error(errors, suggested_state=suggested)
        
        return ValidationResult.ok()

    def ensure_valid_state(self, context: BookingContext) -> bool:
        """
        Проверяет и исправляет состояние контекста при необходимости.
        
        Возвращает True, если контекст был изменён.
        """
        if context.state is None:
            context.state = BookingState.ASK_CHECKIN
            return True
        
        if context.state in (BookingState.DONE, BookingState.CANCELLED):
            return False
        
        result = self.validate_context_for_state(context)
        if not result.is_valid and result.suggested_state:
            old_state = context.state
            context.state = result.suggested_state
            
            # Очищаем указанные поля
            if result.fields_to_clear:
                for field_name in result.fields_to_clear:
                    if hasattr(context, field_name):
                        setattr(context, field_name, None)
            
            logger.warning(
                "Auto-corrected context state from %s to %s due to: %s",
                old_state,
                result.suggested_state,
                ", ".join(result.errors),
            )
            return True
        
        return False

    def get_missing_fields(self, context: BookingContext) -> List[str]:
        """Возвращает список отсутствующих обязательных полей."""
        missing: List[str] = []
        
        if not context.checkin:
            missing.append("checkin")
        if not context.checkout and context.nights is None:
            missing.append("checkout_or_nights")
        if context.adults is None:
            missing.append("adults")
        if context.children is None:
            missing.append("children")
        if (context.children or 0) > 0 and not context.children_ages:
            missing.append("children_ages")
        
        return missing

    def is_ready_for_calculation(self, context: BookingContext) -> bool:
        """Проверяет, готов ли контекст для расчёта."""
        result = self._validate_for_calculation(context)
        return result.is_valid


def get_booking_context_validator() -> BookingContextValidator:
    """Возвращает экземпляр BookingContextValidator."""
    return BookingContextValidator()


__all__ = [
    "BookingContextValidator",
    "ValidationResult",
    "get_booking_context_validator",
    "STATES_REQUIRING_CHECKIN",
    "STATES_REQUIRING_STAY_DURATION",
]
