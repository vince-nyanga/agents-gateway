"""PersistenceBackend protocol — the contract for pluggable persistence backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_gateway.persistence.protocols import (
    AuditRepository,
    ConversationRepository,
    ExecutionRepository,
    ScheduleRepository,
    UserAgentConfigRepository,
    UserRepository,
    UserScheduleRepository,
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

    @property
    def user_repo(self) -> UserRepository: ...

    @property
    def conversation_repo(self) -> ConversationRepository: ...

    @property
    def user_agent_config_repo(self) -> UserAgentConfigRepository: ...

    @property
    def user_schedule_repo(self) -> UserScheduleRepository: ...
