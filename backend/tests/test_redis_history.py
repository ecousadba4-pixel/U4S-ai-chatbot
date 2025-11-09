import asyncio
import time

import pytest

from backend.redis_gateway import REDIS_HISTORY_KEY, RedisHistoryGateway

from backend.tests._helpers import DummyRequest


class InMemoryRedisClient:
    """Минималистичная имитация Redis для проверки логики хранения."""

    def __init__(self) -> None:
        self._storage: dict[str, tuple[str, float | None]] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        expires_at = time.time() + max(int(ttl), 1)
        self._storage[key] = (value, expires_at)

    def get(self, key: str) -> str | None:
        payload = self._storage.get(key)
        if not payload:
            return None
        value, expires_at = payload
        if expires_at is not None and expires_at < time.time():
            self._storage.pop(key, None)
            return None
        return value

    def delete(self, key: str) -> None:
        self._storage.pop(key, None)


@pytest.fixture()
def redis_gateway():
    client = InMemoryRedisClient()
    gateway = RedisHistoryGateway(client, ttl_seconds=60, max_messages=10)
    return gateway, client


def test_redis_gateway_persists_and_retrieves_messages(redis_gateway):
    gateway, client = redis_gateway

    session_id = "session-1"
    history = [
        {"role": "user", "content": "Привет", "timestamp": 1.0},
        {"role": "assistant", "content": "Здравствуйте", "timestamp": 2.0},
    ]

    gateway.write_history(session_id, history, ttl=120)

    key = REDIS_HISTORY_KEY.format(session_id=session_id)
    raw_payload, expires_at = client._storage[key]
    assert expires_at > time.time()
    assert "Привет" in raw_payload

    loaded = gateway.read_history(session_id)
    assert loaded == history

    updated_history = history + [
        {"role": "user", "content": "Как дела?", "timestamp": 3.0},
        {"role": "assistant", "content": "Все отлично", "timestamp": 4.0},
    ]
    gateway.write_history(session_id, updated_history)

    loaded_again = gateway.read_history(session_id)
    assert loaded_again == updated_history[-gateway.max_messages :]


def test_chat_post_reads_history_from_redis(app_module, monkeypatch, redis_gateway):
    gateway, client = redis_gateway
    monkeypatch.setattr(app_module, "REDIS_GATEWAY", gateway)

    payload_first = {
        "sessionId": "thread-1",
        "history": [],
        "question": "Привет",
    }
    response_first = asyncio.run(app_module.chat_post(DummyRequest(payload_first)))
    assert response_first["answer"] == "Ответ"

    stored_after_first = gateway.read_history("thread-1")
    assert [item["role"] for item in stored_after_first[-2:]] == ["user", "assistant"]

    payload_second = {
        "sessionId": "thread-1",
        "history": [],
        "question": "Расскажи подробнее",
    }
    response_second = asyncio.run(app_module.chat_post(DummyRequest(payload_second)))
    assert response_second["answer"] == "Ответ"

    assert len(app_module.CLIENT.calls) >= 2
    second_call_messages = app_module.CLIENT.calls[-1]["input"]
    roles_sequence = [message["role"] for message in second_call_messages]
    assert roles_sequence[:2] == ["system", "user"]
    assert roles_sequence[2] == "assistant"
    assert roles_sequence[-1] == "user"

    stored_after_second = gateway.read_history("thread-1")
    assert [item["role"] for item in stored_after_second[-4:]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
