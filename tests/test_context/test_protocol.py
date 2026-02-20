"""Tests for the ContextRetriever protocol."""

from __future__ import annotations

from agent_gateway.context.protocol import ContextRetriever


class _FakeRetriever:
    """Minimal implementation for protocol conformance testing."""

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        return [f"result for {query}"]

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass


class TestContextRetrieverProtocol:
    def test_conformance(self) -> None:
        """A class implementing all three methods satisfies the protocol."""
        retriever = _FakeRetriever()
        assert isinstance(retriever, ContextRetriever)

    def test_non_conformance(self) -> None:
        """A class missing methods does not satisfy the protocol."""

        class _Incomplete:
            async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
                return []

        assert not isinstance(_Incomplete(), ContextRetriever)
