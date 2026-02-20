"""Shared test fakes for context tests."""

from __future__ import annotations

import pytest


class FakeRetriever:
    """Minimal retriever that returns canned chunks."""

    def __init__(self, chunks: list[str] | None = None) -> None:
        self.chunks = chunks or []
        self.initialized = False
        self.closed = False

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        return self.chunks if self.chunks else [f"chunk:{query}"]

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


class FailingRetriever:
    """Retriever that raises on every method."""

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        raise RuntimeError("retriever error")

    async def initialize(self) -> None:
        raise RuntimeError("init boom")

    async def close(self) -> None:
        raise RuntimeError("close boom")


@pytest.fixture()
def fake_retriever() -> FakeRetriever:
    return FakeRetriever()


@pytest.fixture()
def failing_retriever() -> FailingRetriever:
    return FailingRetriever()
