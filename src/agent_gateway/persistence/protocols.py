"""Protocol definitions for persistence repositories."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from agent_gateway.persistence.domain import (
    AuditLogEntry,
    ConversationMessage,
    ConversationRecord,
    ExecutionRecord,
    ExecutionStep,
    ScheduleRecord,
    UserAgentConfig,
    UserProfile,
    UserScheduleRecord,
)


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

    async def get_with_steps(self, execution_id: str) -> ExecutionRecord | None: ...

    async def list_by_session(self, session_id: str, limit: int = 50) -> list[ExecutionRecord]: ...

    async def cost_by_session(self, session_id: str) -> dict[str, Any]: ...

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        session_id: str | None = None,
        search: str | None = None,
    ) -> list[ExecutionRecord]: ...

    async def count_all(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        session_id: str | None = None,
        search: str | None = None,
    ) -> int: ...

    async def list_conversations_summary(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]: ...

    async def count_conversations(self) -> int: ...

    async def cost_by_day(self, days: int = 30) -> list[dict[str, Any]]: ...

    async def cost_by_agent(self, days: int = 30) -> list[dict[str, Any]]: ...

    async def executions_by_day(self, days: int = 30) -> list[dict[str, Any]]: ...

    async def get_summary_stats(self, days: int = 30) -> dict[str, Any]: ...

    async def get_schedule_stats(self, hours: int = 24) -> dict[str, Any]:
        """Return counts of schedule-linked executions by status in the last N hours.

        Returns: {'total_scheduled': N, 'active_schedules': N,
                  'success': N, 'failed': N, 'running': N}
        """
        ...

    async def list_by_root_execution(self, root_execution_id: str) -> list[ExecutionRecord]: ...

    async def cost_by_root_execution(self, root_execution_id: str) -> float: ...

    async def list_children(self, parent_execution_id: str) -> list[ExecutionRecord]: ...

    async def add_step(self, step: ExecutionStep) -> None: ...


@runtime_checkable
class ScheduleRepository(Protocol):
    """Interface for schedule persistence."""

    async def upsert(self, record: ScheduleRecord) -> None: ...

    async def upsert_batch(self, records: list[ScheduleRecord]) -> None: ...

    async def get(self, schedule_id: str) -> ScheduleRecord | None: ...

    async def list_all(self, agent_id: str | None = None) -> list[ScheduleRecord]: ...

    async def update_last_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime | None,
    ) -> None: ...

    async def update_next_run(
        self,
        schedule_id: str,
        next_run_at: datetime | None,
    ) -> None: ...

    async def update_enabled(self, schedule_id: str, enabled: bool) -> None: ...


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


@runtime_checkable
class UserRepository(Protocol):
    """Interface for user profile persistence."""

    async def upsert(self, profile: UserProfile) -> None: ...

    async def get(self, user_id: str) -> UserProfile | None: ...

    async def delete(self, user_id: str) -> bool: ...


@runtime_checkable
class ConversationRepository(Protocol):
    """Interface for conversation persistence."""

    async def create(self, record: ConversationRecord) -> None: ...

    async def get(self, conversation_id: str) -> ConversationRecord | None: ...

    async def list_by_user(
        self,
        user_id: str,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationRecord]: ...

    async def update(self, record: ConversationRecord) -> None: ...

    async def add_message(self, message: ConversationMessage) -> None: ...

    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ConversationMessage]: ...

    async def update_summary(self, conversation_id: str, summary: str) -> None: ...

    async def delete(self, conversation_id: str) -> bool: ...


@runtime_checkable
class UserAgentConfigRepository(Protocol):
    """Interface for per-user agent config persistence."""

    async def get(self, user_id: str, agent_id: str) -> UserAgentConfig | None: ...

    async def upsert(self, config: UserAgentConfig) -> None: ...

    async def delete(self, user_id: str, agent_id: str) -> bool: ...

    async def list_by_user(self, user_id: str) -> list[UserAgentConfig]: ...

    async def list_by_agent(self, agent_id: str) -> list[UserAgentConfig]: ...


@runtime_checkable
class UserScheduleRepository(Protocol):
    """Interface for per-user schedule persistence."""

    async def create(self, record: UserScheduleRecord) -> None: ...

    async def get(self, schedule_id: str) -> UserScheduleRecord | None: ...

    async def list_by_user(self, user_id: str) -> list[UserScheduleRecord]: ...

    async def update_enabled(self, schedule_id: str, enabled: bool) -> None: ...

    async def update_last_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime | None,
    ) -> None: ...

    async def delete(self, schedule_id: str) -> bool: ...
