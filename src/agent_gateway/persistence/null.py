"""Null persistence implementation for when database is unavailable or disabled.

Same interface as the real repositories, but does nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_gateway.persistence.domain import (
    AuditLogEntry,
    ExecutionRecord,
    ExecutionStep,
    ScheduleRecord,
)


class NullExecutionRepository:
    """No-op execution repository — used when persistence is disabled."""

    async def create(self, execution: ExecutionRecord) -> None:
        pass

    async def get(self, execution_id: str) -> ExecutionRecord | None:
        return None

    async def update_status(self, execution_id: str, status: str, **fields: Any) -> None:
        pass

    async def update_result(
        self,
        execution_id: str,
        result: dict[str, Any],
        usage: dict[str, Any],
    ) -> None:
        pass

    async def list_by_agent(self, agent_id: str, limit: int = 50) -> list[ExecutionRecord]:
        return []

    async def list_by_schedule(self, schedule_id: str, limit: int = 20) -> list[ExecutionRecord]:
        return []

    async def add_step(self, step: ExecutionStep) -> None:
        pass


class NullScheduleRepository:
    """No-op schedule repository — used when persistence is disabled."""

    def __init__(self) -> None:
        self._store: dict[str, ScheduleRecord] = {}

    async def upsert(self, record: ScheduleRecord) -> None:
        self._store[record.id] = record

    async def get(self, schedule_id: str) -> ScheduleRecord | None:
        return self._store.get(schedule_id)

    async def list_all(self, agent_id: str | None = None) -> list[ScheduleRecord]:
        records = [r for r in self._store.values() if r.deleted_at is None]
        if agent_id is not None:
            records = [r for r in records if r.agent_id == agent_id]
        return records

    async def update_last_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime | None,
    ) -> None:
        record = self._store.get(schedule_id)
        if record is not None:
            record.last_run_at = last_run_at
            record.next_run_at = next_run_at

    async def update_next_run(
        self,
        schedule_id: str,
        next_run_at: datetime | None,
    ) -> None:
        record = self._store.get(schedule_id)
        if record is not None:
            record.next_run_at = next_run_at

    async def update_enabled(self, schedule_id: str, enabled: bool) -> None:
        record = self._store.get(schedule_id)
        if record is not None:
            record.enabled = enabled

    async def soft_delete(self, schedule_id: str) -> None:
        from datetime import UTC

        record = self._store.get(schedule_id)
        if record is not None:
            record.deleted_at = datetime.now(UTC)


class NullAuditRepository:
    """No-op audit repository — used when persistence is disabled."""

    async def log(
        self,
        event_type: str,
        actor: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        pass

    async def list_recent(self, limit: int = 100) -> list[AuditLogEntry]:
        return []
