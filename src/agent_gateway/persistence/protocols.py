"""Protocol definitions for persistence repositories."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent_gateway.persistence.models import AuditLogEntry, ExecutionRecord, ExecutionStep


@runtime_checkable
class ExecutionRepository(Protocol):
    """Interface for execution persistence."""

    async def create(self, execution: ExecutionRecord) -> None: ...

    async def get(self, execution_id: str) -> ExecutionRecord | None: ...

    async def update_status(self, execution_id: str, status: str, **fields: Any) -> None: ...

    async def update_result(
        self,
        execution_id: str,
        result: dict[str, Any],
        usage: dict[str, Any],
    ) -> None: ...

    async def list_by_agent(self, agent_id: str, limit: int = 50) -> list[ExecutionRecord]: ...

    async def add_step(self, step: ExecutionStep) -> None: ...


@runtime_checkable
class AuditRepository(Protocol):
    """Interface for audit log persistence."""

    async def log(
        self,
        event_type: str,
        actor: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None: ...

    async def list_recent(self, limit: int = 100) -> list[AuditLogEntry]: ...
