"""Null persistence implementation for when database is unavailable or disabled.

Same interface as the real repositories, but does nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_gateway.persistence.domain import (
    AuditLogEntry,
    ConversationMessage,
    ConversationRecord,
    ExecutionRecord,
    ExecutionStep,
    McpServerConfig,
    NotificationDeliveryRecord,
    ScheduleRecord,
    UserAgentConfig,
    UserProfile,
    UserScheduleRecord,
)

_EMPTY_ANALYTICS: list[dict[str, Any]] = []


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

    async def get_with_steps(self, execution_id: str) -> ExecutionRecord | None:
        return None

    async def list_by_session(
        self,
        session_id: str,
        limit: int = 50,
        user_id: str | None = None,
    ) -> list[ExecutionRecord]:
        return []

    async def cost_by_session(self, session_id: str) -> dict[str, Any]:
        return {
            "execution_count": 0,
            "total_cost_usd": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        session_id: str | None = None,
        search: str | None = None,
        min_cost: float | None = None,
        max_cost: float | None = None,
        schedule_id: str | None = None,
    ) -> list[ExecutionRecord]:
        return []

    async def count_all(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        session_id: str | None = None,
        search: str | None = None,
        min_cost: float | None = None,
        max_cost: float | None = None,
        schedule_id: str | None = None,
    ) -> int:
        return 0

    async def list_conversations_summary(
        self, limit: int = 50, offset: int = 0, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def count_conversations(self, user_id: str | None = None) -> int:
        return 0

    async def cost_by_day(self, days: int = 30) -> list[dict[str, Any]]:
        return _EMPTY_ANALYTICS

    async def cost_by_agent(self, days: int = 30) -> list[dict[str, Any]]:
        return _EMPTY_ANALYTICS

    async def executions_by_day(self, days: int = 30) -> list[dict[str, Any]]:
        return _EMPTY_ANALYTICS

    async def get_summary_stats(self, days: int = 30) -> dict[str, Any]:
        return {
            "total_executions": 0,
            "total_cost_usd": 0.0,
            "success_count": 0,
            "avg_duration_ms": 0.0,
        }

    async def get_schedule_stats(self, hours: int = 24) -> dict[str, Any]:
        return {
            "total_scheduled": 0,
            "active_schedules": 0,
            "success": 0,
            "failed": 0,
            "running": 0,
        }

    async def list_by_root_execution(self, root_execution_id: str) -> list[ExecutionRecord]:
        return []

    async def cost_by_root_execution(self, root_execution_id: str) -> float:
        return 0.0

    async def list_children(self, parent_execution_id: str) -> list[ExecutionRecord]:
        return []

    async def add_step(self, step: ExecutionStep) -> None:
        pass


class NullScheduleRepository:
    """No-op schedule repository — used when persistence is disabled."""

    def __init__(self) -> None:
        self._store: dict[str, ScheduleRecord] = {}

    async def upsert(self, record: ScheduleRecord) -> None:
        self._store[record.id] = record

    async def upsert_batch(self, records: list[ScheduleRecord]) -> None:
        for record in records:
            existing = self._store.get(record.id)
            if existing is not None and getattr(existing, "source", "workspace") == "admin":
                continue  # Never overwrite admin schedules during workspace sync
            self._store[record.id] = record

    async def get(self, schedule_id: str) -> ScheduleRecord | None:
        return self._store.get(schedule_id)

    async def list_all(self, agent_id: str | None = None) -> list[ScheduleRecord]:
        records = [r for r in self._store.values() if r.deleted_at is None]
        if agent_id is not None:
            records = [r for r in records if r.agent_id == agent_id]
        return records

    async def soft_delete(self, schedule_id: str) -> None:
        record = self._store.get(schedule_id)
        if record is not None:
            record.deleted_at = datetime.now(UTC)

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

    async def update_schedule(
        self,
        schedule_id: str,
        cron_expr: str,
        message: str,
        timezone: str,
        next_run_at: datetime | None = None,
        *,
        instructions: str | None = None,
    ) -> None:
        record = self._store.get(schedule_id)
        if record is not None:
            record.cron_expr = cron_expr
            record.message = message
            record.timezone = timezone
            if instructions is not None:
                record.instructions = instructions or None
            record.next_run_at = next_run_at


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


class NullUserRepository:
    """No-op user repository — used when persistence is disabled."""

    async def upsert(self, profile: UserProfile) -> None:
        pass

    async def get(self, user_id: str) -> UserProfile | None:
        return None

    async def delete(self, user_id: str) -> bool:
        return False


class NullConversationRepository:
    """No-op conversation repository — used when persistence is disabled."""

    async def create(self, record: ConversationRecord) -> None:
        pass

    async def get(self, conversation_id: str) -> ConversationRecord | None:
        return None

    async def list_by_user(
        self,
        user_id: str,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationRecord]:
        return []

    async def update(self, record: ConversationRecord) -> None:
        pass

    async def add_message(self, message: ConversationMessage) -> None:
        pass

    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ConversationMessage]:
        return []

    async def update_summary(self, conversation_id: str, summary: str) -> None:
        pass

    async def delete(self, conversation_id: str) -> bool:
        return False


class NullUserAgentConfigRepository:
    """No-op user agent config repository — used when persistence is disabled."""

    async def get(self, user_id: str, agent_id: str) -> UserAgentConfig | None:
        return None

    async def upsert(self, config: UserAgentConfig) -> None:
        pass

    async def delete(self, user_id: str, agent_id: str) -> bool:
        return False

    async def list_by_user(self, user_id: str) -> list[UserAgentConfig]:
        return []

    async def list_by_agent(self, agent_id: str) -> list[UserAgentConfig]:
        return []


class NullNotificationRepository:
    """No-op notification repository — used when persistence is disabled."""

    async def create(self, record: NotificationDeliveryRecord) -> None:
        pass

    async def list_recent(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        agent_id: str | None = None,
        channel: str | None = None,
        execution_id: str | None = None,
    ) -> list[NotificationDeliveryRecord]:
        return []

    async def count(
        self,
        *,
        status: str | None = None,
        agent_id: str | None = None,
        channel: str | None = None,
        execution_id: str | None = None,
    ) -> int:
        return 0

    async def get(self, record_id: int) -> NotificationDeliveryRecord | None:
        return None

    async def update_status(
        self,
        record_id: int,
        *,
        status: str,
        attempts: int,
        last_error: str | None = None,
        delivered_at: datetime | None = None,
    ) -> None:
        pass


class NullUserScheduleRepository:
    """No-op user schedule repository — used when persistence is disabled."""

    async def create(self, record: UserScheduleRecord) -> None:
        pass

    async def get(self, schedule_id: str) -> UserScheduleRecord | None:
        return None

    async def list_by_user(self, user_id: str) -> list[UserScheduleRecord]:
        return []

    async def update_enabled(self, schedule_id: str, enabled: bool) -> None:
        pass

    async def update_last_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime | None,
    ) -> None:
        pass

    async def delete(self, schedule_id: str) -> bool:
        return False


class NullMcpServerRepository:
    """No-op MCP server repository when persistence is disabled.

    Returns empty results for all queries. When persistence is disabled,
    the _pending_mcp_servers list on Gateway is the ONLY source of MCP
    server configs.
    """

    async def list_all(self) -> list[McpServerConfig]:
        return []

    async def get_by_name(self, name: str) -> McpServerConfig | None:
        return None

    async def get_by_id(self, server_id: str) -> McpServerConfig | None:
        return None

    async def upsert(self, config: McpServerConfig) -> McpServerConfig:
        return config

    async def delete(self, server_id: str) -> bool:
        return False

    async def list_enabled(self) -> list[McpServerConfig]:
        return []
