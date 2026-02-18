"""Shared SQLAlchemy infrastructure for SQL persistence backends.

Uses imperative mapping so domain dataclasses remain ORM-free.
Each backend creates its own registry and metadata instance to avoid
conflicts when multiple Gateway instances exist in the same process.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import registry, relationship

from agent_gateway.persistence.domain import (
    AuditLogEntry,
    ExecutionRecord,
    ExecutionStep,
    ScheduleRecord,
)

if TYPE_CHECKING:
    from agent_gateway.persistence.protocols import AuditRepository, ExecutionRepository

logger = logging.getLogger(__name__)


def build_metadata(table_prefix: str = "", schema: str | None = None) -> MetaData:
    """Build MetaData with naming convention and optional schema."""
    return MetaData(
        schema=schema,
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


def build_tables(metadata: MetaData, prefix: str = "") -> dict[str, Table]:
    """Define all persistence tables with optional name prefix."""
    executions = Table(
        f"{prefix}executions",
        metadata,
        Column("id", String, primary_key=True),
        Column("agent_id", String, nullable=False),
        Column("status", String, nullable=False, default="queued"),
        Column("message", Text, nullable=False, default=""),
        Column("context", JSON),
        Column("options", JSON),
        Column("result", JSON),
        Column("error", Text),
        Column("usage", JSON),
        Column("started_at", DateTime(timezone=True)),
        Column("completed_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}executions_agent_id", "agent_id"),
    )

    execution_steps = Table(
        f"{prefix}execution_steps",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column(
            "execution_id",
            String,
            ForeignKey(f"{prefix}executions.id"),
            nullable=False,
        ),
        Column("step_type", String, nullable=False),
        Column("sequence", Integer, nullable=False),
        Column("data", JSON),
        Column("duration_ms", Integer, default=0),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}execution_steps_execution_id", "execution_id"),
    )

    audit_log = Table(
        f"{prefix}audit_log",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("event_type", String, nullable=False),
        Column("actor", String),
        Column("resource_type", String),
        Column("resource_id", String),
        Column("metadata", JSON),
        Column("ip_address", String),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}audit_log_event_type", "event_type"),
    )

    schedules = Table(
        f"{prefix}schedules",
        metadata,
        Column("id", String, primary_key=True),
        Column("agent_id", String, nullable=False),
        Column("name", String, nullable=False),
        Column("cron_expr", String, nullable=False),
        Column("message", Text, nullable=False),
        Column("context", JSON),
        Column("enabled", Boolean, default=True),
        Column("timezone", String, default="UTC"),
        Column("last_run_at", DateTime(timezone=True)),
        Column("next_run_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}schedules_agent_id", "agent_id"),
        Index(
            f"ix_{prefix}schedules_next_run",
            "next_run_at",
            postgresql_where=Column("enabled") == True,  # noqa: E712
        ),
    )

    return {
        "executions": executions,
        "execution_steps": execution_steps,
        "audit_log": audit_log,
        "schedules": schedules,
    }


def configure_mappers(mapper_registry: registry, tables: dict[str, Table]) -> None:
    """Wire SQLAlchemy to plain domain dataclasses via imperative mapping.

    Must be called exactly once per registry instance.
    """
    mapper_registry.map_imperatively(
        ExecutionRecord,
        tables["executions"],
        properties={
            "steps": relationship(
                ExecutionStep,
                back_populates="execution",
                cascade="all, delete-orphan",
            ),
        },
    )

    mapper_registry.map_imperatively(
        ExecutionStep,
        tables["execution_steps"],
        properties={
            "execution": relationship(ExecutionRecord, back_populates="steps"),
        },
    )

    mapper_registry.map_imperatively(AuditLogEntry, tables["audit_log"])

    mapper_registry.map_imperatively(ScheduleRecord, tables["schedules"])


class SqlBackend:
    """Base class for SQL persistence backends.

    Not a Protocol — provides concrete shared logic for SQLite and PostgreSQL.
    Subclasses provide the engine with backend-specific configuration.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        metadata: MetaData,
        mapper_registry: registry,
        tables: dict[str, Table],
    ) -> None:
        self._engine = engine
        self._metadata = metadata
        self._mapper_registry = mapper_registry
        self._tables = tables
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        configure_mappers(mapper_registry, tables)

        # Import here to avoid circular imports
        from agent_gateway.persistence.backends.sql.repository import (
            AuditRepository as AuditRepo,
        )
        from agent_gateway.persistence.backends.sql.repository import (
            ExecutionRepository as ExecRepo,
        )

        self._execution_repo: ExecutionRepository = ExecRepo(self._session_factory)
        self._audit_repo: AuditRepository = AuditRepo(self._session_factory)

    async def initialize(self) -> None:
        """Create all tables if they don't exist. Idempotent."""
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all)
        logger.info("Database tables initialized")

    async def dispose(self) -> None:
        """Clean up mapper registry and close the engine."""
        self._mapper_registry.dispose()
        await self._engine.dispose()

    @property
    def execution_repo(self) -> ExecutionRepository:
        return self._execution_repo

    @property
    def audit_repo(self) -> AuditRepository:
        return self._audit_repo
