"""SQL-backed memory backend with per-user memory support.

Requires the persistence SQL backend to be initialized (tables created
by ``build_tables()`` in ``persistence.backends.sql.base``).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemoryType,
)

logger = logging.getLogger(__name__)


class SqlMemoryRepository:
    """SQL-backed memory repository with per-user scoping.

    Supports both global agent memories (user_id IS NULL) and
    per-user memories (user_id = <value>).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, record: MemoryRecord) -> None:
        """Upsert a memory record."""
        async with self._session_factory() as session:
            existing = await session.get(MemoryRecord, record.id)
            if existing is None:
                session.add(record)
            else:
                existing.content = record.content
                existing.memory_type = record.memory_type
                existing.source = record.source
                existing.importance = record.importance
                existing.user_id = record.user_id
                existing.updated_at = record.updated_at
            await session.commit()

    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory by ID."""
        async with self._session_factory() as session:
            record = await session.get(MemoryRecord, memory_id)
            if record is not None and record.agent_id == agent_id:
                return record
            return None

    async def list_memories(
        self,
        agent_id: str,
        *,
        user_id: str | None = None,
        include_global: bool = True,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List memories with optional user/type filters."""
        async with self._session_factory() as session:
            stmt = select(MemoryRecord).where(
                MemoryRecord.agent_id == agent_id  # type: ignore[arg-type, misc]
            )

            stmt = self._apply_user_filter(stmt, user_id, include_global)

            if memory_type is not None:
                stmt = stmt.where(MemoryRecord.memory_type == memory_type)

            stmt = (
                stmt.order_by(MemoryRecord.updated_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        user_id: str | None = None,
        include_global: bool = True,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        """Keyword search — case-insensitive matching (mirrors file backend)."""
        # Fetch all matching records, then score in Python
        records = await self.list_memories(
            agent_id,
            user_id=user_id,
            include_global=include_global,
            memory_type=memory_type,
            limit=200,
        )

        query_lower = query.lower()
        query_words = query_lower.split()

        results: list[MemorySearchResult] = []
        for r in records:
            content_lower = r.content.lower()
            matches = sum(1 for w in query_words if w in content_lower)
            if matches > 0:
                score = matches / len(query_words) if query_words else 0.0
                # Boost per-user memories when both scopes are included
                if user_id and r.user_id == user_id:
                    score += 0.1
                results.append(MemorySearchResult(record=r, score=score))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    async def delete(self, agent_id: str, memory_id: str) -> bool:
        """Delete a memory. Returns True if it existed."""
        async with self._session_factory() as session:
            record = await session.get(MemoryRecord, memory_id)
            if record is None or record.agent_id != agent_id:
                return False
            await session.delete(record)
            await session.commit()
            return True

    async def delete_all(self, agent_id: str, user_id: str | None = None) -> int:
        """Delete all memories for an agent (optionally scoped to user)."""
        async with self._session_factory() as session:
            stmt = select(MemoryRecord).where(
                MemoryRecord.agent_id == agent_id  # type: ignore[arg-type, misc]
            )
            if user_id is not None:
                stmt = stmt.where(
                    MemoryRecord.user_id == user_id  # type: ignore[arg-type, misc]
                )
            result = await session.execute(stmt)
            records = list(result.scalars().all())
            for record in records:
                await session.delete(record)
            await session.commit()
            return len(records)

    async def count(self, agent_id: str, user_id: str | None = None) -> int:
        """Count memories for an agent (optionally scoped to user)."""
        async with self._session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(MemoryRecord)
                .where(
                    MemoryRecord.agent_id == agent_id  # type: ignore[arg-type, misc]
                )
            )
            if user_id is not None:
                stmt = stmt.where(
                    MemoryRecord.user_id == user_id  # type: ignore[arg-type, misc]
                )
            result = await session.execute(stmt)
            return result.scalar_one()

    @staticmethod
    def _apply_user_filter(stmt: Any, user_id: str | None, include_global: bool) -> Any:
        """Apply user scoping filter to a query."""
        if user_id is None:
            # Global only
            stmt = stmt.where(
                MemoryRecord.user_id.is_(None)  # type: ignore[union-attr]
            )
        elif include_global:
            # Both user-specific and global
            stmt = stmt.where(
                or_(
                    MemoryRecord.user_id == user_id,  # type: ignore[arg-type, misc]
                    MemoryRecord.user_id.is_(None),  # type: ignore[union-attr]
                )
            )
        else:
            # User-specific only
            stmt = stmt.where(MemoryRecord.user_id == user_id)
        return stmt


class SqlMemoryBackend:
    """SQL-backed memory backend.

    Uses the persistence layer's session factory for database access.
    The memories table is created by ``build_tables()`` in the SQL base module.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._repo = SqlMemoryRepository(session_factory)

    async def initialize(self) -> None:
        """No-op — tables are created by the persistence backend."""
        pass

    async def dispose(self) -> None:
        """No-op — connection lifecycle managed by the persistence backend."""
        pass

    @property
    def memory_repo(self) -> SqlMemoryRepository:
        return self._repo
