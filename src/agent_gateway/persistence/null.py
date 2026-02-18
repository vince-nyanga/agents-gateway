"""Null persistence implementation for when database is unavailable or disabled.

Same interface as the real repositories, but does nothing.
"""

from __future__ import annotations

from typing import Any

from agent_gateway.persistence.models import AuditLogEntry, ExecutionRecord, ExecutionStep


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

    async def add_step(self, step: ExecutionStep) -> None:
        pass


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
