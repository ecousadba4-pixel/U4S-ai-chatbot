"""Вспомогательные классы для тестирования."""

import json


class DummyRequest:
    """Mock для HTTP-запросов в тестах."""

    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload

    async def body(self):
        return json.dumps(self._payload).encode("utf-8")
