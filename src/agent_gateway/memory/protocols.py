"""Memory protocols — structural typing contracts for pluggable memory backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemoryType,
)


@runtime_checkable
class MemoryRepository(Protocol):
    """Storage and retrieval contract for agent memories.

    Implementations must handle CRUD and search.
    Satisfied structurally (duck typing) — no inheritance required.
    """

    async def save(self, record: MemoryRecord) -> None:
        """Upsert a memory record (insert or update by id)."""
        ...

    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory by ID."""
        ...

    async def list_memories(
        self,
        agent_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List memories with optional type filter, ordered by updated_at desc."""
        ...

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        """Search memories by relevance. Backend decides search strategy."""
        ...

    async def delete(self, agent_id: str, memory_id: str) -> bool:
        """Delete a memory. Returns True if it existed."""
        ...

    async def delete_all(self, agent_id: str) -> int:
        """Delete all memories for an agent. Returns count deleted."""
        ...

    async def count(self, agent_id: str) -> int:
        """Count memories for an agent."""
        ...


@runtime_checkable
class MemoryBackend(Protocol):
    """Top-level memory backend with lifecycle management.

    Mirrors the PersistenceBackend pattern — provides lifecycle hooks
    and access to the underlying repository.
    """

    async def initialize(self) -> None:
        """Create tables/indexes/files. Must be idempotent."""
        ...

    async def dispose(self) -> None:
        """Close connections and release resources."""
        ...

    @property
    def memory_repo(self) -> MemoryRepository:
        """Access the memory repository."""
        ...
