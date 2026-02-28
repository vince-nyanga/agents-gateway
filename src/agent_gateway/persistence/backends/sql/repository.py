"""CRUD operations for SQL persistence backends (SQLite, PostgreSQL)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

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


def _is_postgres(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """Check if the session factory is bound to a PostgreSQL engine."""
    bind = session_factory.kw.get("bind")
    if bind is None:
        return False
    return "postgresql" in str(bind.url)


def _normalize_row(row_mapping: Any) -> dict[str, Any]:
    """Convert non-JSON-serializable types from raw SQL results."""
    from decimal import Decimal

    result: dict[str, Any] = {}
    for k, v in dict(row_mapping).items():
        if isinstance(v, date) and not isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result


def _json_field(column: str, key: str, *, is_postgres: bool) -> str:
    """Return a SQL expression to extract a JSON field, dialect-aware."""
    if is_postgres:
        return f"CAST(({column}::json)->>'{key}' AS NUMERIC)"
    return f"CAST(json_extract({column}, '$.{key}') AS REAL)"


class ExecutionRepository:
    """CRUD operations for execution records and steps."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._pg = _is_postgres(session_factory)

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

    async def add_step(self, step: ExecutionStep) -> None:
        """Insert a new execution step."""
        async with self._session_factory() as session:
            session.add(step)
            await session.commit()

    async def get_with_steps(self, execution_id: str) -> ExecutionRecord | None:
        """Fetch an execution by ID with all its steps eagerly loaded."""
        async with self._session_factory() as session:
            stmt = (
                select(ExecutionRecord)
                .where(ExecutionRecord.id == execution_id)  # type: ignore[arg-type]
                .options(selectinload(ExecutionRecord.steps))  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return result.scalars().first()

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
        """List executions across all agents, most recent first."""
        async with self._session_factory() as session:
            stmt = select(ExecutionRecord).order_by(
                ExecutionRecord.created_at.desc()  # type: ignore[union-attr]
            )
            if agent_id is not None:
                stmt = stmt.where(
                    ExecutionRecord.agent_id == agent_id  # type: ignore[arg-type]
                )
            if status is not None:
                stmt = stmt.where(
                    ExecutionRecord.status == status  # type: ignore[arg-type]
                )
            if since is not None:
                stmt = stmt.where(
                    ExecutionRecord.created_at >= since  # type: ignore[operator,arg-type]
                )
            if until is not None:
                stmt = stmt.where(
                    ExecutionRecord.created_at <= until  # type: ignore[operator,arg-type]
                )
            if session_id is not None:
                stmt = stmt.where(
                    ExecutionRecord.session_id == session_id  # type: ignore[arg-type]
                )
            if schedule_id is not None:
                stmt = stmt.where(
                    ExecutionRecord.schedule_id == schedule_id  # type: ignore[arg-type]
                )
            if search is not None:
                like_pattern = f"%{search}%"
                stmt = stmt.where(
                    (ExecutionRecord.message.ilike(like_pattern))  # type: ignore[attr-defined]
                    | (ExecutionRecord.id.like(like_pattern))  # type: ignore[attr-defined]
                    | (ExecutionRecord.session_id.like(like_pattern))  # type: ignore[union-attr]
                    | (ExecutionRecord.error.ilike(like_pattern))  # type: ignore[union-attr]
                )
            if min_cost is not None or max_cost is not None:
                cost_expr = _json_field("usage", "cost_usd", is_postgres=self._pg)
                if min_cost is not None:
                    stmt = stmt.where(
                        text(f"{cost_expr} >= :min_cost").bindparams(min_cost=min_cost)
                    )
                if max_cost is not None:
                    stmt = stmt.where(
                        text(f"{cost_expr} <= :max_cost").bindparams(max_cost=max_cost)
                    )
            stmt = stmt.limit(limit).offset(offset)
            result = await session.execute(stmt)
            return list(result.scalars().all())

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
        """Count executions with optional filters."""
        async with self._session_factory() as session:
            stmt = select(func.count()).select_from(ExecutionRecord)
            if schedule_id is not None:
                stmt = stmt.where(
                    ExecutionRecord.schedule_id == schedule_id  # type: ignore[arg-type]
                )
            if agent_id is not None:
                stmt = stmt.where(
                    ExecutionRecord.agent_id == agent_id  # type: ignore[arg-type]
                )
            if status is not None:
                stmt = stmt.where(
                    ExecutionRecord.status == status  # type: ignore[arg-type]
                )
            if since is not None:
                stmt = stmt.where(
                    ExecutionRecord.created_at >= since  # type: ignore[operator,arg-type]
                )
            if until is not None:
                stmt = stmt.where(
                    ExecutionRecord.created_at <= until  # type: ignore[operator,arg-type]
                )
            if session_id is not None:
                stmt = stmt.where(
                    ExecutionRecord.session_id == session_id  # type: ignore[arg-type]
                )
            if search is not None:
                like_pattern = f"%{search}%"
                stmt = stmt.where(
                    (ExecutionRecord.message.ilike(like_pattern))  # type: ignore[attr-defined]
                    | (ExecutionRecord.id.like(like_pattern))  # type: ignore[attr-defined]
                    | (ExecutionRecord.session_id.like(like_pattern))  # type: ignore[union-attr]
                    | (ExecutionRecord.error.ilike(like_pattern))  # type: ignore[union-attr]
                )
            if min_cost is not None or max_cost is not None:
                cost_expr = _json_field("usage", "cost_usd", is_postgres=self._pg)
                if min_cost is not None:
                    stmt = stmt.where(
                        text(f"{cost_expr} >= :min_cost").bindparams(min_cost=min_cost)
                    )
                if max_cost is not None:
                    stmt = stmt.where(
                        text(f"{cost_expr} <= :max_cost").bindparams(max_cost=max_cost)
                    )
            result = await session.execute(stmt)
            return result.scalar_one()

    async def list_by_session(
        self,
        session_id: str,
        limit: int = 50,
        user_id: str | None = None,
    ) -> list[ExecutionRecord]:
        """List executions for a session, most recent first."""
        async with self._session_factory() as session:
            stmt = (
                select(ExecutionRecord)
                .where(ExecutionRecord.session_id == session_id)  # type: ignore[arg-type]
                .order_by(ExecutionRecord.created_at.desc())  # type: ignore[union-attr]
                .limit(limit)
            )
            if user_id is not None:
                stmt = stmt.where(ExecutionRecord.user_id == user_id)  # type: ignore[arg-type]
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def cost_by_session(self, session_id: str) -> dict[str, Any]:
        """Aggregate cost and token usage for all executions in a session."""
        cost = _json_field("usage", "cost_usd", is_postgres=self._pg)
        inp = _json_field("usage", "input_tokens", is_postgres=self._pg)
        out = _json_field("usage", "output_tokens", is_postgres=self._pg)
        async with self._session_factory() as session:
            stmt = text(f"""
                SELECT
                    COUNT(*) as execution_count,
                    COALESCE(SUM({cost}), 0) as total_cost_usd,
                    COALESCE(SUM({inp}), 0) as total_input_tokens,
                    COALESCE(SUM({out}), 0) as total_output_tokens
                FROM executions
                WHERE session_id = :session_id
                  AND usage IS NOT NULL
                """)
            result = await session.execute(stmt, {"session_id": session_id})
            row = result.one()
            return _normalize_row(row._mapping)

    async def list_conversations_summary(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List conversations grouped by session_id with aggregated stats."""
        cost = _json_field("usage", "cost_usd", is_postgres=self._pg)
        inp = _json_field("usage", "input_tokens", is_postgres=self._pg)
        out = _json_field("usage", "output_tokens", is_postgres=self._pg)
        user_filter = " AND user_id = :user_id" if user_id is not None else ""
        async with self._session_factory() as session:
            stmt = text(f"""
                SELECT
                    session_id,
                    agent_id,
                    COUNT(*) as execution_count,
                    COALESCE(SUM({cost}), 0) as total_cost_usd,
                    COALESCE(SUM({inp}), 0) as total_input_tokens,
                    COALESCE(SUM({out}), 0) as total_output_tokens,
                    MIN(created_at) as first_activity,
                    MAX(created_at) as last_activity
                FROM executions
                WHERE session_id IS NOT NULL{user_filter}
                GROUP BY session_id, agent_id
                ORDER BY last_activity DESC
                LIMIT :limit OFFSET :offset
                """)
            params: dict[str, Any] = {"limit": limit, "offset": offset}
            if user_id is not None:
                params["user_id"] = user_id
            result = await session.execute(stmt, params)
            return [_normalize_row(row._mapping) for row in result]

    async def count_conversations(self, user_id: str | None = None) -> int:
        """Count distinct conversations (unique session_ids)."""
        user_filter = " AND user_id = :user_id" if user_id is not None else ""
        async with self._session_factory() as session:
            stmt = text(f"""
                SELECT COUNT(DISTINCT session_id) as cnt
                FROM executions
                WHERE session_id IS NOT NULL{user_filter}
                """)
            params: dict[str, Any] = {}
            if user_id is not None:
                params["user_id"] = user_id
            result = await session.execute(stmt, params)
            return int(result.scalar_one())

    async def list_by_root_execution(self, root_execution_id: str) -> list[ExecutionRecord]:
        """Return all executions in a workflow tree."""
        async with self._session_factory() as session:
            stmt = (
                select(ExecutionRecord)
                .where(
                    ExecutionRecord.root_execution_id == root_execution_id  # type: ignore[arg-type]
                )
                .order_by(
                    ExecutionRecord.delegation_depth,  # type: ignore[arg-type]
                    ExecutionRecord.created_at,  # type: ignore[arg-type]
                )
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def cost_by_root_execution(self, root_execution_id: str) -> float:
        """Aggregated cost across the entire workflow tree."""
        cost = _json_field("usage", "cost_usd", is_postgres=self._pg)
        async with self._session_factory() as session:
            stmt = text(f"""
                SELECT COALESCE(SUM({cost}), 0) as total_cost
                FROM executions
                WHERE root_execution_id = :root_id
                  AND usage IS NOT NULL
                """)
            result = await session.execute(stmt, {"root_id": root_execution_id})
            val = result.scalar()
            return float(val) if val else 0.0

    async def list_children(self, parent_execution_id: str) -> list[ExecutionRecord]:
        """Return direct child executions of a parent."""
        async with self._session_factory() as session:
            stmt = (
                select(ExecutionRecord)
                .where(
                    ExecutionRecord.parent_execution_id == parent_execution_id  # type: ignore[arg-type]
                )
                .order_by(ExecutionRecord.created_at)  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def cost_by_day(self, days: int = 30) -> list[dict[str, Any]]:
        """Daily cost aggregation for the last N days."""
        since = datetime.now(UTC) - timedelta(days=days)
        cost = _json_field("usage", "cost_usd", is_postgres=self._pg)
        inp = _json_field("usage", "input_tokens", is_postgres=self._pg)
        out = _json_field("usage", "output_tokens", is_postgres=self._pg)
        async with self._session_factory() as session:
            stmt = text(f"""
                SELECT
                    date(created_at) as day,
                    COUNT(*) as execution_count,
                    SUM({cost}) as total_cost_usd,
                    SUM({inp}) as total_input_tokens,
                    SUM({out}) as total_output_tokens
                FROM executions
                WHERE created_at >= :since
                  AND usage IS NOT NULL
                GROUP BY date(created_at)
                ORDER BY day ASC
                """)
            since_param = since if self._pg else since.isoformat()
            result = await session.execute(stmt, {"since": since_param})
            return [_normalize_row(row._mapping) for row in result]

    async def cost_by_agent(self, days: int = 30) -> list[dict[str, Any]]:
        """Per-agent cost aggregation for the last N days."""
        since = datetime.now(UTC) - timedelta(days=days)
        cost = _json_field("usage", "cost_usd", is_postgres=self._pg)
        inp = _json_field("usage", "input_tokens", is_postgres=self._pg)
        out = _json_field("usage", "output_tokens", is_postgres=self._pg)

        if self._pg:
            duration_expr = "EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000"
        else:
            duration_expr = "(julianday(completed_at) - julianday(started_at)) * 86400000"

        async with self._session_factory() as session:
            stmt = text(f"""
                SELECT
                    agent_id,
                    COUNT(*) as execution_count,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success_count,
                    SUM({cost}) as total_cost_usd,
                    SUM({inp}) as total_input_tokens,
                    SUM({out}) as total_output_tokens,
                    AVG(CASE WHEN status = 'completed' AND started_at IS NOT NULL
                             AND completed_at IS NOT NULL
                             THEN {duration_expr} ELSE NULL END) as avg_duration_ms
                FROM executions
                WHERE created_at >= :since
                  AND usage IS NOT NULL
                GROUP BY agent_id
                ORDER BY total_cost_usd DESC
                """)
            since_param = since if self._pg else since.isoformat()
            result = await session.execute(stmt, {"since": since_param})
            return [_normalize_row(row._mapping) for row in result]

    async def get_summary_stats(self, days: int = 30) -> dict[str, Any]:
        """Aggregate summary stats for the last N days."""
        since = datetime.now(UTC) - timedelta(days=days)
        cost = _json_field("usage", "cost_usd", is_postgres=self._pg)

        # Calculate duration in ms.
        # PostgreSQL: EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000
        # SQLite: (julianday(completed_at) - julianday(started_at)) * 86400000
        if self._pg:
            duration_expr = "EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000"
        else:
            duration_expr = "(julianday(completed_at) - julianday(started_at)) * 86400000"

        async with self._session_factory() as session:
            stmt = text(f"""
                SELECT
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success_count,
                    COALESCE(SUM({cost}), 0) as total_cost_usd,
                    COALESCE(AVG(CASE WHEN status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL 
                                 THEN {duration_expr} ELSE NULL END), 0) as avg_duration_ms
                FROM executions
                WHERE created_at >= :since
            """)
            since_param = since if self._pg else since.isoformat()
            result = await session.execute(stmt, {"since": since_param})
            row = result.one()
            return _normalize_row(row._mapping)

    async def get_schedule_stats(self, hours: int = 24) -> dict[str, Any]:
        """Return counts of schedule-linked executions by status in the last N hours."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        async with self._session_factory() as session:
            stmt = text("""
                SELECT
                    COUNT(*) as total_scheduled,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END) as running
                FROM executions
                WHERE schedule_id IS NOT NULL
                  AND created_at >= :since
            """)
            since_param = since if self._pg else since.isoformat()
            result = await session.execute(stmt, {"since": since_param})
            row = result.one()
            stats = _normalize_row(row._mapping)

            # Count active schedules from both schedules and user_schedules tables
            active_stmt = text("""
                SELECT
                    (SELECT COUNT(*) FROM schedules
                     WHERE enabled = :enabled AND deleted_at IS NULL)
                    +
                    (SELECT COUNT(*) FROM user_schedules
                     WHERE enabled = :enabled)
                    AS active_schedules
            """)
            active_result = await session.execute(active_stmt, {"enabled": True})
            active_count = int(active_result.scalar_one())
            stats["active_schedules"] = active_count
            return stats

    async def executions_by_day(self, days: int = 30) -> list[dict[str, Any]]:
        """Daily execution count by status for the last N days."""
        since = datetime.now(UTC) - timedelta(days=days)
        async with self._session_factory() as session:
            stmt = text(
                """
                SELECT
                    date(created_at) as day,
                    COUNT(*) as count,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count
                FROM executions
                WHERE created_at >= :since
                GROUP BY date(created_at)
                ORDER BY day ASC
                """
            )
            since_param = since if self._pg else since.isoformat()
            result = await session.execute(stmt, {"since": since_param})
            return [_normalize_row(row._mapping) for row in result]


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
                existing.instructions = record.instructions
                existing.input = record.input
                existing.enabled = record.enabled
                existing.timezone = record.timezone
                existing.source = record.source
                existing.next_run_at = record.next_run_at
                existing.deleted_at = None  # un-delete if re-added
            await session.commit()

    async def upsert_batch(self, records: list[ScheduleRecord]) -> None:
        """Upsert multiple schedule records in a single transaction."""
        if not records:
            return
        async with self._session_factory() as session:
            for record in records:
                existing = await session.get(ScheduleRecord, record.id)
                if existing is None:
                    session.add(record)
                else:
                    if getattr(existing, "source", "workspace") == "admin":
                        continue  # Never overwrite admin schedules during workspace sync
                    existing.name = record.name
                    existing.cron_expr = record.cron_expr
                    existing.message = record.message
                    existing.instructions = record.instructions
                    existing.input = record.input
                    existing.enabled = record.enabled
                    existing.timezone = record.timezone
                    existing.source = record.source
                    existing.next_run_at = record.next_run_at
                    existing.deleted_at = None
            await session.commit()

    async def soft_delete(self, schedule_id: str) -> None:
        """Soft-delete a schedule by setting deleted_at."""
        async with self._session_factory() as session:
            record = await session.get(ScheduleRecord, schedule_id)
            if record is not None:
                record.deleted_at = datetime.now(UTC)
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
        """Update schedule configuration fields."""
        async with self._session_factory() as session:
            record = await session.get(ScheduleRecord, schedule_id)
            if record is None:
                return
            record.cron_expr = cron_expr
            record.message = message
            record.timezone = timezone
            if instructions is not None:
                record.instructions = instructions or None
            record.next_run_at = next_run_at
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


class UserRepository:
    """CRUD operations for user profiles."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(self, profile: UserProfile) -> None:
        """Insert or update a user profile."""
        async with self._session_factory() as session:
            existing = await session.get(UserProfile, profile.user_id)
            if existing is None:
                session.add(profile)
            else:
                existing.display_name = profile.display_name
                existing.email = profile.email
                existing.metadata = profile.metadata
                existing.last_seen_at = profile.last_seen_at
            await session.commit()

    async def get(self, user_id: str) -> UserProfile | None:
        """Fetch a user profile by ID."""
        async with self._session_factory() as session:
            return await session.get(UserProfile, user_id)

    async def delete(self, user_id: str) -> bool:
        """Delete a user profile. Returns True if it existed."""
        async with self._session_factory() as session:
            profile = await session.get(UserProfile, user_id)
            if profile is None:
                return False
            await session.delete(profile)
            await session.commit()
            return True


class ConversationRepository:
    """CRUD operations for conversations and messages."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, record: ConversationRecord) -> None:
        """Insert a new conversation record."""
        async with self._session_factory() as session:
            session.add(record)
            await session.commit()

    async def get(self, conversation_id: str) -> ConversationRecord | None:
        """Fetch a conversation by ID."""
        async with self._session_factory() as session:
            return await session.get(ConversationRecord, conversation_id)

    async def list_by_user(
        self,
        user_id: str,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationRecord]:
        """List conversations for a user, most recent first."""
        async with self._session_factory() as session:
            stmt = (
                select(ConversationRecord)
                .where(
                    ConversationRecord.user_id == user_id  # type: ignore[arg-type]
                )
                .order_by(
                    ConversationRecord.updated_at.desc()  # type: ignore[union-attr]
                )
            )
            if agent_id is not None:
                stmt = stmt.where(
                    ConversationRecord.agent_id == agent_id  # type: ignore[arg-type]
                )
            stmt = stmt.limit(limit).offset(offset)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update(self, record: ConversationRecord) -> None:
        """Update an existing conversation record."""
        async with self._session_factory() as session:
            existing = await session.get(ConversationRecord, record.conversation_id)
            if existing is None:
                return
            existing.title = record.title
            existing.summary = record.summary
            existing.message_count = record.message_count
            existing.updated_at = record.updated_at
            existing.ended_at = record.ended_at
            await session.commit()

    async def add_message(self, message: ConversationMessage) -> None:
        """Insert a message into a conversation."""
        async with self._session_factory() as session:
            session.add(message)
            await session.commit()

    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ConversationMessage]:
        """Get messages for a conversation, oldest first."""
        async with self._session_factory() as session:
            stmt = (
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == conversation_id  # type: ignore[arg-type]
                )
                .order_by(
                    ConversationMessage.created_at  # type: ignore[arg-type]
                )
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_summary(self, conversation_id: str, summary: str) -> None:
        """Update the summary of a conversation."""
        async with self._session_factory() as session:
            record = await session.get(ConversationRecord, conversation_id)
            if record is None:
                return
            record.summary = summary
            await session.commit()

    async def delete(self, conversation_id: str) -> bool:
        """Delete a conversation and its messages. Returns True if it existed."""
        async with self._session_factory() as session:
            record = await session.get(ConversationRecord, conversation_id)
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True


class UserAgentConfigRepository:
    """CRUD operations for per-user agent configuration."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, user_id: str, agent_id: str) -> UserAgentConfig | None:
        """Fetch a user's config for an agent."""
        async with self._session_factory() as session:
            return await session.get(UserAgentConfig, (user_id, agent_id))

    async def upsert(self, config: UserAgentConfig) -> None:
        """Insert or update a user agent config."""
        async with self._session_factory() as session:
            existing = await session.get(UserAgentConfig, (config.user_id, config.agent_id))
            if existing is None:
                session.add(config)
            else:
                existing.instructions = config.instructions
                existing.config_values = config.config_values
                existing.encrypted_secrets = config.encrypted_secrets
                existing.setup_completed = config.setup_completed
                existing.updated_at = config.updated_at
            await session.commit()

    async def delete(self, user_id: str, agent_id: str) -> bool:
        """Delete a user's config for an agent. Returns True if it existed."""
        async with self._session_factory() as session:
            record = await session.get(UserAgentConfig, (user_id, agent_id))
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True

    async def list_by_user(self, user_id: str) -> list[UserAgentConfig]:
        """List all configs for a user."""
        async with self._session_factory() as session:
            stmt = select(UserAgentConfig).where(
                UserAgentConfig.user_id == user_id  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_by_agent(self, agent_id: str) -> list[UserAgentConfig]:
        """List all user configs for an agent."""
        async with self._session_factory() as session:
            stmt = select(UserAgentConfig).where(
                UserAgentConfig.agent_id == agent_id  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())


class UserScheduleRepository:
    """CRUD operations for per-user schedules."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, record: UserScheduleRecord) -> None:
        async with self._session_factory() as session:
            session.add(record)
            await session.commit()

    async def get(self, schedule_id: str) -> UserScheduleRecord | None:
        async with self._session_factory() as session:
            return await session.get(UserScheduleRecord, schedule_id)

    async def list_by_user(self, user_id: str) -> list[UserScheduleRecord]:
        async with self._session_factory() as session:
            stmt = select(UserScheduleRecord).where(
                UserScheduleRecord.user_id == user_id  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_enabled(self, schedule_id: str, enabled: bool) -> None:
        async with self._session_factory() as session:
            record = await session.get(UserScheduleRecord, schedule_id)
            if record is not None:
                record.enabled = enabled
                await session.commit()

    async def update_last_run(
        self,
        schedule_id: str,
        last_run_at: datetime,
        next_run_at: datetime | None,
    ) -> None:
        async with self._session_factory() as session:
            record = await session.get(UserScheduleRecord, schedule_id)
            if record is not None:
                record.last_run_at = last_run_at
                record.next_run_at = next_run_at
                await session.commit()

    async def delete(self, schedule_id: str) -> bool:
        async with self._session_factory() as session:
            record = await session.get(UserScheduleRecord, schedule_id)
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True


class NotificationRepository:
    """CRUD operations for notification delivery records."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, record: NotificationDeliveryRecord) -> None:
        """Insert a new notification delivery record."""
        async with self._session_factory() as session:
            session.add(record)
            await session.commit()

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
        """List notification records with optional filters, most recent first."""
        async with self._session_factory() as session:
            stmt = select(NotificationDeliveryRecord).order_by(
                NotificationDeliveryRecord.created_at.desc()  # type: ignore[union-attr]
            )
            stmt = self._apply_filters(stmt, status, agent_id, channel, execution_id)
            stmt = stmt.limit(limit).offset(offset)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count(
        self,
        *,
        status: str | None = None,
        agent_id: str | None = None,
        channel: str | None = None,
        execution_id: str | None = None,
    ) -> int:
        """Count notification records matching filters."""
        async with self._session_factory() as session:
            stmt = select(func.count()).select_from(NotificationDeliveryRecord)
            stmt = self._apply_filters(stmt, status, agent_id, channel, execution_id)
            result = await session.execute(stmt)
            return int(result.scalar_one())

    async def get(self, record_id: int) -> NotificationDeliveryRecord | None:
        """Fetch a single notification delivery record by ID."""
        async with self._session_factory() as session:
            return await session.get(NotificationDeliveryRecord, record_id)

    async def update_status(
        self,
        record_id: int,
        *,
        status: str,
        attempts: int,
        last_error: str | None = None,
        delivered_at: datetime | None = None,
    ) -> None:
        """Update the status of a notification delivery record."""
        async with self._session_factory() as session:
            record = await session.get(NotificationDeliveryRecord, record_id)
            if record is not None:
                record.status = status
                record.attempts = attempts
                record.last_error = last_error
                record.delivered_at = delivered_at
                await session.commit()

    @staticmethod
    def _apply_filters(
        stmt: Any,
        status: str | None,
        agent_id: str | None,
        channel: str | None,
        execution_id: str | None,
    ) -> Any:
        if status is not None:
            stmt = stmt.where(NotificationDeliveryRecord.status == status)
        if agent_id is not None:
            stmt = stmt.where(NotificationDeliveryRecord.agent_id == agent_id)
        if channel is not None:
            stmt = stmt.where(NotificationDeliveryRecord.channel == channel)
        if execution_id is not None:
            stmt = stmt.where(NotificationDeliveryRecord.execution_id == execution_id)
        return stmt


class McpServerRepository:
    """CRUD operations for MCP server configurations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_all(self) -> list[McpServerConfig]:
        """List all MCP server configurations."""
        async with self._session_factory() as session:
            stmt = select(McpServerConfig).order_by(
                McpServerConfig.created_at  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_by_name(self, name: str) -> McpServerConfig | None:
        """Fetch an MCP server config by unique name."""
        async with self._session_factory() as session:
            stmt = select(McpServerConfig).where(
                McpServerConfig.name == name  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_by_id(self, server_id: str) -> McpServerConfig | None:
        """Fetch an MCP server config by ID."""
        async with self._session_factory() as session:
            return await session.get(McpServerConfig, server_id)

    async def upsert(self, config: McpServerConfig) -> McpServerConfig:
        """Insert or update an MCP server config."""
        async with self._session_factory() as session:
            existing = await session.get(McpServerConfig, config.id)
            if existing is None:
                session.add(config)
            else:
                existing.name = config.name
                existing.transport = config.transport
                existing.command = config.command
                existing.args = config.args
                existing.encrypted_env = config.encrypted_env
                existing.url = config.url
                existing.headers = config.headers
                existing.encrypted_credentials = config.encrypted_credentials
                existing.enabled = config.enabled
                existing.updated_at = config.updated_at
            await session.commit()
            return config

    async def delete(self, server_id: str) -> bool:
        """Delete an MCP server config by ID."""
        async with self._session_factory() as session:
            existing = await session.get(McpServerConfig, server_id)
            if existing is None:
                return False
            await session.delete(existing)
            await session.commit()
            return True

    async def list_enabled(self) -> list[McpServerConfig]:
        """List all enabled MCP server configurations."""
        async with self._session_factory() as session:
            stmt = (
                select(McpServerConfig)
                .where(McpServerConfig.enabled == True)  # type: ignore[arg-type]  # noqa: E712
                .order_by(McpServerConfig.created_at)  # type: ignore[arg-type]
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
