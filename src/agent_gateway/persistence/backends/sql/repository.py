"""CRUD operations for SQL persistence backends (SQLite, PostgreSQL)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_gateway.persistence.domain import (
    AuditLogEntry,
    ExecutionRecord,
    ExecutionStep,
    ScheduleRecord,
)


class ExecutionRepository:
    """CRUD operations for execution records and steps."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, execution: ExecutionRecord) -> None:
        """Insert a new execution record."""
        async with self._session_factory() as session:
            session.add(execution)
            await session.commit()

    async def get(self, execution_id: str) -> ExecutionRecord | None:
        """Fetch an execution by ID."""
        async with self._session_factory() as session:
            return await session.get(ExecutionRecord, execution_id)

    async def update_status(
        self,
        execution_id: str,
        status: str,
        **fields: Any,
    ) -> None:
        """Update the status and optional fields of an execution."""
        async with self._session_factory() as session:
            record = await session.get(ExecutionRecord, execution_id)
            if record is None:
                return
            record.status = status
            for key, value in fields.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            await session.commit()

    async def update_result(
        self,
        execution_id: str,
        result: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        """Update the result and usage of a completed execution."""
        async with self._session_factory() as session:
            record = await session.get(ExecutionRecord, execution_id)
            if record is None:
                return
            record.result = result
            record.usage = usage
            record.completed_at = datetime.now(UTC)
            await session.commit()

    async def list_by_agent(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> list[ExecutionRecord]:
        """List executions for an agent, most recent first."""
        async with self._session_factory() as session:
            stmt = (
                select(ExecutionRecord)
                .where(ExecutionRecord.agent_id == agent_id)  # type: ignore[arg-type]
                .order_by(ExecutionRecord.created_at.desc())  # type: ignore[union-attr]
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_by_schedule(
        self,
        schedule_id: str,
        limit: int = 20,
    ) -> list[ExecutionRecord]:
        """List executions triggered by a schedule, most recent first."""
        async with self._session_factory() as session:
            stmt = (
                select(ExecutionRecord)
                .where(ExecutionRecord.schedule_id == schedule_id)  # type: ignore[arg-type]
                .order_by(ExecutionRecord.created_at.desc())  # type: ignore[union-attr]
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def add_step(self, step: ExecutionStep) -> None:
        """Insert a new execution step."""
        async with self._session_factory() as session:
            session.add(step)
            await session.commit()


class ScheduleRepository:
    """CRUD operations for schedule records."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(self, record: ScheduleRecord) -> None:
        """Insert or update a schedule record."""
        async with self._session_factory() as session:
            existing = await session.get(ScheduleRecord, record.id)
            if existing is None:
                session.add(record)
            else:
                existing.agent_id = record.agent_id
                existing.name = record.name
                existing.cron_expr = record.cron_expr
                existing.message = record.message
                existing.context = record.context
                existing.enabled = record.enabled
                existing.timezone = record.timezone
                existing.next_run_at = record.next_run_at
                existing.deleted_at = None  # un-delete if re-added
            await session.commit()

    async def get(self, schedule_id: str) -> ScheduleRecord | None:
        """Fetch a schedule by ID."""
        async with self._session_factory() as session:
            return await session.get(ScheduleRecord, schedule_id)

    async def list_all(self, agent_id: str | None = None) -> list[ScheduleRecord]:
        """List all non-deleted schedules, optionally filtered by agent."""
        async with self._session_factory() as session:
            stmt = select(ScheduleRecord).where(
                ScheduleRecord.deleted_at.is_(None)  # type: ignore[union-attr]
            )
            if agent_id is not None:
                stmt = stmt.where(
                    ScheduleRecord.agent_id == agent_id  # type: ignore[arg-type]
                )
            stmt = stmt.order_by(ScheduleRecord.created_at)  # type: ignore[arg-type]
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_last_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime | None,
    ) -> None:
        """Update the last and next run times for a schedule."""
        async with self._session_factory() as session:
            record = await session.get(ScheduleRecord, schedule_id)
            if record is None:
                return
            record.last_run_at = last_run_at
            record.next_run_at = next_run_at
            await session.commit()

    async def update_next_run(
        self,
        schedule_id: str,
        next_run_at: datetime | None,
    ) -> None:
        """Update only the next run time for a schedule."""
        async with self._session_factory() as session:
            record = await session.get(ScheduleRecord, schedule_id)
            if record is None:
                return
            record.next_run_at = next_run_at
            await session.commit()

    async def update_enabled(self, schedule_id: str, enabled: bool) -> None:
        """Update the enabled state of a schedule."""
        async with self._session_factory() as session:
            record = await session.get(ScheduleRecord, schedule_id)
            if record is None:
                return
            record.enabled = enabled
            await session.commit()

    async def soft_delete(self, schedule_id: str) -> None:
        """Mark a schedule as deleted without removing it."""
        async with self._session_factory() as session:
            record = await session.get(ScheduleRecord, schedule_id)
            if record is None:
                return
            record.deleted_at = datetime.now(UTC)
            await session.commit()


class AuditRepository:
    """CRUD operations for audit log entries."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def log(
        self,
        event_type: str,
        actor: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Write an audit log entry."""
        entry = AuditLogEntry(
            event_type=event_type,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
            ip_address=ip_address,
        )
        async with self._session_factory() as session:
            session.add(entry)
            await session.commit()

    async def list_recent(self, limit: int = 100) -> list[AuditLogEntry]:
        """List recent audit log entries, most recent first."""
        async with self._session_factory() as session:
            stmt = (
                select(AuditLogEntry)
                .order_by(AuditLogEntry.created_at.desc())  # type: ignore[union-attr]
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
