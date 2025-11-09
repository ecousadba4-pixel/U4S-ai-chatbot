from __future__ import annotations

import os

import pytest

os.environ.setdefault("YANDEX_API_KEY", "dummy-key")
os.environ.setdefault("YANDEX_FOLDER_ID", "dummy-folder")
os.environ.setdefault("VECTOR_STORE_ID", "dummy-store")

import backend.rag as rag_module


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def advance(self, delta: float) -> None:
        self.value += float(delta)

    def __call__(self) -> float:
        return self.value


class DummyVectorConfig:
    can_use_vector_store = True


class DummyVectorClient:
    def __init__(self) -> None:
        self.config = DummyVectorConfig()
        self.meta_calls: list[str] = []
        self.content_calls: list[str] = []

    def list_vector_files(self) -> list[dict]:  # pragma: no cover - не используется
        return []

    def fetch_vector_meta(self, file_id: str) -> dict:
        self.meta_calls.append(file_id)
        return {"filename": f"{file_id}.md"}

    def fetch_vector_content(self, file_id: str) -> str:
        self.content_calls.append(file_id)
        return f"content:{file_id}"


@pytest.fixture()
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr(rag_module.time, "monotonic", clock)
    return clock


def test_fetch_file_refreshes_expired_cache(fake_clock: FakeClock) -> None:
    client = DummyVectorClient()
    gateway = rag_module.VectorStoreGateway(client, ttl_seconds=10.0, max_cached_files=4)

    meta1 = gateway.fetch_file("doc1")
    assert client.meta_calls == ["doc1"]
    assert meta1[1] == "content:doc1"

    fake_clock.advance(5.0)
    meta2 = gateway.fetch_file("doc1")
    assert client.meta_calls == ["doc1"]
    assert meta2 == meta1

    fake_clock.advance(6.0)
    meta3 = gateway.fetch_file("doc1")
    assert client.meta_calls == ["doc1", "doc1"]
    assert meta3 == meta1
    assert len(gateway._file_cache) == 1


def test_fetch_file_prunes_old_entries(fake_clock: FakeClock) -> None:
    client = DummyVectorClient()
    gateway = rag_module.VectorStoreGateway(client, ttl_seconds=100.0, max_cached_files=2)

    gateway.fetch_file("one")
    fake_clock.advance(1.0)
    gateway.fetch_file("two")
    fake_clock.advance(1.0)
    gateway.fetch_file("three")

    assert set(gateway._file_cache.keys()) == {"two", "three"}
