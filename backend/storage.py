"""Локальное хранилище истории и контекста без Redis."""

from __future__ import annotations

from typing import Any, Sequence


MAX_HISTORY_MESSAGES = 50


class InMemoryStorage:
    """Простое in-memory хранилище переписки и контекста диалога."""

    def __init__(self, *, max_messages: int = MAX_HISTORY_MESSAGES) -> None:
        self.max_messages = max(1, int(max_messages))
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._context: dict[str, dict[str, Any]] = {}

    # --- история сообщений ---
    def read_history(self, session_id: str) -> list[dict[str, Any]]:
        if not session_id:
            return []
        return [dict(item) for item in self._history.get(session_id, [])]

    def write_history(
        self, session_id: str, messages: Sequence[dict[str, Any]], ttl: int | None = None
    ) -> None:
        if not session_id:
            return
        limited = [dict(item) for item in messages][-self.max_messages :]
        self._history[session_id] = limited

    def delete_history(self, session_id: str) -> None:
        if not session_id:
            return
        self._history.pop(session_id, None)

    # --- контекст диалога ---
    def read_context(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            return {}
        return dict(self._context.get(session_id, {}))

    def write_context(self, session_id: str, context: dict[str, Any], ttl: int | None = None) -> None:
        if not session_id:
            return
        self._context[session_id] = dict(context or {})

    def delete_context(self, session_id: str) -> None:
        if not session_id:
            return
        self._context.pop(session_id, None)


__all__ = ["InMemoryStorage", "MAX_HISTORY_MESSAGES"]
