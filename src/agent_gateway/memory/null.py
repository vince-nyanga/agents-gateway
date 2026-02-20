"""Null memory implementation for when memory is disabled.

Same interface as real backends, but does nothing.
"""

from __future__ import annotations

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemoryType,
)


class NullMemoryRepository:
    """No-op repository — used when memory is disabled."""

    async def save(self, record: MemoryRecord) -> None:
        pass

    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None:
        return None

    async def list_memories(
        self,
        agent_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        return []

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        return []

    async def delete(self, agent_id: str, memory_id: str) -> bool:
        return False

    async def delete_all(self, agent_id: str) -> int:
        return 0

    async def count(self, agent_id: str) -> int:
        return 0


class NullMemoryBackend:
    """No-op backend — used when memory is disabled."""

    def __init__(self) -> None:
        self._repo = NullMemoryRepository()

    async def initialize(self) -> None:
        pass

    async def dispose(self) -> None:
        pass

    @property
    def memory_repo(self) -> NullMemoryRepository:
        return self._repo
