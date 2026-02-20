"""Tests for RetrieverRegistry."""

from __future__ import annotations

import pytest

from agent_gateway.context.registry import RetrieverRegistry


class _FakeRetriever:
    def __init__(self) -> None:
        self.initialized = False
        self.closed = False

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        return [f"chunk:{query}"]

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


class _FailingRetriever:
    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        raise RuntimeError("boom")

    async def initialize(self) -> None:
        raise RuntimeError("init boom")

    async def close(self) -> None:
        raise RuntimeError("close boom")


class TestRetrieverRegistry:
    def test_register_and_has(self) -> None:
        reg = RetrieverRegistry()
        r = _FakeRetriever()
        reg.register("my-retriever", r)
        assert reg.has("my-retriever")
        assert not reg.has("nonexistent")

    def test_duplicate_name_raises(self) -> None:
        reg = RetrieverRegistry()
        reg.register("dup", _FakeRetriever())
        with pytest.raises(ValueError, match="already registered"):
            reg.register("dup", _FakeRetriever())

    def test_resolve_for_agent(self) -> None:
        reg = RetrieverRegistry()
        r1 = _FakeRetriever()
        r2 = _FakeRetriever()
        reg.register("r1", r1)
        reg.register("r2", r2)

        resolved = reg.resolve_for_agent(["r1", "r2"])
        assert resolved == [r1, r2]

    def test_resolve_unknown_skipped(self) -> None:
        reg = RetrieverRegistry()
        reg.register("known", _FakeRetriever())

        resolved = reg.resolve_for_agent(["known", "unknown"])
        assert len(resolved) == 1

    async def test_initialize_all(self) -> None:
        reg = RetrieverRegistry()
        r = _FakeRetriever()
        reg.register("r", r)
        await reg.initialize_all()
        assert r.initialized

    async def test_close_all(self) -> None:
        reg = RetrieverRegistry()
        r = _FakeRetriever()
        reg.register("r", r)
        await reg.close_all()
        assert r.closed

    async def test_initialize_failure_does_not_crash(self) -> None:
        reg = RetrieverRegistry()
        reg.register("bad", _FailingRetriever())
        reg.register("good", _FakeRetriever())
        # Should not raise
        await reg.initialize_all()

    async def test_close_failure_does_not_crash(self) -> None:
        reg = RetrieverRegistry()
        reg.register("bad", _FailingRetriever())
        # Should not raise
        await reg.close_all()
