"""PersistenceBackend protocol — the contract for pluggable persistence backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_gateway.persistence.protocols import (
    AuditRepository,
    ExecutionRepository,
    ScheduleRepository,
)


@runtime_checkable
class PersistenceBackend(Protocol):
    """Contract for a pluggable persistence backend.

    Implementations must provide repository instances and lifecycle methods.
    Satisfied structurally (duck typing) — no inheritance required.
    """

    async def initialize(self) -> None:
        """Create tables/collections/indexes. Must be idempotent."""
        ...

    async def dispose(self) -> None:
        """Close connections and release resources."""
        ...

    @property
    def execution_repo(self) -> ExecutionRepository: ...

    @property
    def audit_repo(self) -> AuditRepository: ...

    @property
    def schedule_repo(self) -> ScheduleRepository: ...
