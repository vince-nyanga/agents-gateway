"""Tests for null memory backend."""

from __future__ import annotations

import pytest

from agent_gateway.memory.domain import MemoryRecord
from agent_gateway.memory.null import NullMemoryBackend, NullMemoryRepository


class TestNullMemoryRepository:
    @pytest.fixture
    def repo(self) -> NullMemoryRepository:
        return NullMemoryRepository()

    async def test_save_is_noop(self, repo: NullMemoryRepository) -> None:
        record = MemoryRecord(id="a", agent_id="x", content="test")
        await repo.save(record)
        # No error, no state change
        assert await repo.count("x") == 0

    async def test_get_returns_none(self, repo: NullMemoryRepository) -> None:
        assert await repo.get("agent", "id") is None

    async def test_list_returns_empty(self, repo: NullMemoryRepository) -> None:
        assert await repo.list_memories("agent") == []

    async def test_search_returns_empty(self, repo: NullMemoryRepository) -> None:
        assert await repo.search("agent", "query") == []

    async def test_delete_returns_false(self, repo: NullMemoryRepository) -> None:
        assert await repo.delete("agent", "id") is False

    async def test_delete_all_returns_zero(self, repo: NullMemoryRepository) -> None:
        assert await repo.delete_all("agent") == 0

    async def test_count_returns_zero(self, repo: NullMemoryRepository) -> None:
        assert await repo.count("agent") == 0


class TestNullMemoryBackend:
    async def test_lifecycle(self) -> None:
        backend = NullMemoryBackend()
        await backend.initialize()
        assert backend.memory_repo is not None
        await backend.dispose()
