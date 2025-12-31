"""
Сервис управления навигацией в FSM бронирования.

Централизует логику отмены и возврата по состояниям FSM,
убирая дублирование из основного BookingFsmService.
"""

from __future__ import annotations

import logging
from typing import Set

from app.booking.fsm import BookingContext, BookingState

logger = logging.getLogger(__name__)


# Команды отмены бронирования
CANCEL_COMMANDS: Set[str] = frozenset({
    "отмена",
    "отменить",
    "стоп",
    "cancel",
    "отмени",
    "начать заново",
    "начнём заново",
    "начнем заново",
    "сброс",
    "сбросить",
})

# Команды возврата назад
BACK_COMMANDS: Set[str] = frozenset({
    "назад",
    "вернись",
    "вернуться",
    "back",
})

# Порядок состояний FSM для навигации
FSM_STATE_ORDER: list[BookingState] = [
    BookingState.ASK_CHECKIN,
    BookingState.ASK_NIGHTS_OR_CHECKOUT,
    BookingState.ASK_ADULTS,
    BookingState.ASK_CHILDREN_COUNT,
    BookingState.ASK_CHILDREN_AGES,
    BookingState.CALCULATE,
    BookingState.AWAITING_USER_DECISION,
    BookingState.CONFIRM_BOOKING,
]

# Состояния, требующие наличия checkin
STATES_REQUIRING_CHECKIN: Set[BookingState] = frozenset({
    BookingState.ASK_NIGHTS_OR_CHECKOUT,
    BookingState.ASK_ADULTS,
    BookingState.ASK_CHILDREN_COUNT,
    BookingState.ASK_CHILDREN_AGES,
    BookingState.CALCULATE,
})


class BookingNavigationService:
    """Сервис для управления навигацией по состояниям FSM бронирования."""

    def is_cancel_command(self, normalized_text: str) -> bool:
        """Проверяет, является ли команда командой отмены."""
        return normalized_text in CANCEL_COMMANDS

    def is_back_command(self, normalized_text: str) -> bool:
        """Проверяет, является ли команда командой возврата назад."""
        return normalized_text in BACK_COMMANDS

    def handle_cancel(self, context: BookingContext) -> str:
        """
        Обрабатывает команду отмены бронирования.
        
        Returns:
            Сообщение для пользователя об отмене.
        """
        context.state = BookingState.CANCELLED
        logger.info("Booking cancelled for context: %s", context.compact())
        return "Отменяю бронирование. Если понадобится помощь, напишите."

    def go_back(self, context: BookingContext) -> BookingState:
        """
        Возвращает FSM на предыдущее состояние, очищая соответствующие данные.
        
        Returns:
            Новое состояние после возврата.
        """
        previous = self._get_previous_state(context.state)
        
        # Очищаем данные в зависимости от целевого состояния
        if previous == BookingState.ASK_CHECKIN:
            context.checkin = None
            context.nights = None
            context.checkout = None
        elif previous == BookingState.ASK_NIGHTS_OR_CHECKOUT:
            context.nights = None
            context.checkout = None
        elif previous == BookingState.ASK_ADULTS:
            context.adults = None
        elif previous == BookingState.ASK_CHILDREN_COUNT:
            context.children = None
            context.children_ages = []
        elif previous == BookingState.ASK_CHILDREN_AGES:
            context.children_ages = []
        
        context.state = previous
        logger.debug(
            "Navigated back from %s to %s",
            context.state,
            previous,
        )
        return previous

    def _get_previous_state(self, state: BookingState | None) -> BookingState:
        """Возвращает предыдущее состояние FSM."""
        if state is None or state not in FSM_STATE_ORDER:
            return BookingState.ASK_CHECKIN
        
        idx = FSM_STATE_ORDER.index(state)
        return FSM_STATE_ORDER[idx - 1] if idx > 0 else BookingState.ASK_CHECKIN

    def get_next_state(self, state: BookingState | None) -> BookingState | None:
        """Возвращает следующее состояние FSM."""
        if state is None:
            return BookingState.ASK_CHECKIN
        
        if state not in FSM_STATE_ORDER:
            return None
        
        idx = FSM_STATE_ORDER.index(state)
        if idx < len(FSM_STATE_ORDER) - 1:
            return FSM_STATE_ORDER[idx + 1]
        return None

    def requires_checkin(self, state: BookingState | None) -> bool:
        """Проверяет, требует ли состояние наличия даты заезда."""
        return state in STATES_REQUIRING_CHECKIN

    def reset_to_start(self, context: BookingContext) -> None:
        """Сбрасывает контекст до начального состояния."""
        context.checkin = None
        context.nights = None
        context.checkout = None
        context.adults = None
        context.children = None
        context.children_ages = []
        context.room_type = None
        context.promo = None
        context.offers = []
        context.last_offer_index = 0
        context.retries = {}
        context.state = BookingState.ASK_CHECKIN
        logger.info("Reset booking context to initial state")

    def reset_dates(self, context: BookingContext) -> None:
        """Сбрасывает только даты бронирования."""
        context.checkin = None
        context.checkout = None
        context.nights = None
        context.state = BookingState.ASK_CHECKIN
        logger.debug("Reset dates in booking context")

    def reset_guests(self, context: BookingContext) -> None:
        """Сбрасывает только данные о гостях."""
        context.adults = None
        context.children = None
        context.children_ages = []
        context.state = BookingState.ASK_ADULTS
        logger.debug("Reset guests in booking context")


def get_booking_navigation_service() -> BookingNavigationService:
    """Возвращает экземпляр BookingNavigationService."""
    return BookingNavigationService()


__all__ = [
    "BookingNavigationService",
    "get_booking_navigation_service",
    "CANCEL_COMMANDS",
    "BACK_COMMANDS",
    "FSM_STATE_ORDER",
    "STATES_REQUIRING_CHECKIN",
]
