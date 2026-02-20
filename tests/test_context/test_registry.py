"""Tests for RetrieverRegistry."""

from __future__ import annotations

import pytest

from agent_gateway.context.registry import RetrieverRegistry

from .conftest import FailingRetriever, FakeRetriever


class TestRetrieverRegistry:
    def test_register_and_resolve(self) -> None:
        reg = RetrieverRegistry()
        r = FakeRetriever()
        reg.register("my-retriever", r)
        assert reg.resolve_for_agent(["my-retriever"]) == [r]
        assert reg.resolve_for_agent(["nonexistent"]) == []

    def test_duplicate_name_raises(self) -> None:
        reg = RetrieverRegistry()
        reg.register("dup", FakeRetriever())
        with pytest.raises(ValueError, match="already registered"):
            reg.register("dup", FakeRetriever())

    def test_resolve_for_agent(self) -> None:
        reg = RetrieverRegistry()
        r1 = FakeRetriever()
        r2 = FakeRetriever()
        reg.register("r1", r1)
        reg.register("r2", r2)

        resolved = reg.resolve_for_agent(["r1", "r2"])
        assert resolved == [r1, r2]

    def test_resolve_unknown_skipped(self) -> None:
        reg = RetrieverRegistry()
        reg.register("known", FakeRetriever())

        resolved = reg.resolve_for_agent(["known", "unknown"])
        assert len(resolved) == 1

    async def test_initialize_all(self) -> None:
        reg = RetrieverRegistry()
        r = FakeRetriever()
        reg.register("r", r)
        await reg.initialize_all()
        assert r.initialized

    async def test_close_all(self) -> None:
        reg = RetrieverRegistry()
        r = FakeRetriever()
        reg.register("r", r)
        await reg.close_all()
        assert r.closed

    async def test_initialize_failure_does_not_crash(self) -> None:
        reg = RetrieverRegistry()
        reg.register("bad", FailingRetriever())
        reg.register("good", FakeRetriever())
        # Should not raise
        await reg.initialize_all()

    async def test_close_failure_does_not_crash(self) -> None:
        reg = RetrieverRegistry()
        reg.register("bad", FailingRetriever())
        # Should not raise
        await reg.close_all()
