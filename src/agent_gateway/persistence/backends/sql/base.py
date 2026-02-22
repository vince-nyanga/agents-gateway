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
    Float,
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

from agent_gateway.memory.domain import MemoryRecord
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

if TYPE_CHECKING:
    from agent_gateway.persistence.protocols import (
        AuditRepository,
        ConversationRepository,
        ExecutionRepository,
        ScheduleRepository,
        UserAgentConfigRepository,
        UserRepository,
        UserScheduleRepository,
    )

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
        Column("input", JSON),
        Column("options", JSON),
        Column("result", JSON),
        Column("error", Text),
        Column("usage", JSON),
        Column("session_id", String, nullable=True),
        Column("schedule_id", String, nullable=True),
        Column("schedule_name", String, nullable=True),
        Column("started_at", DateTime(timezone=True)),
        Column("completed_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}executions_agent_id", "agent_id"),
        Index(f"ix_{prefix}executions_session_id", "session_id"),
        Index(f"ix_{prefix}executions_schedule_id", "schedule_id"),
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
        Column("input", JSON),
        Column("enabled", Boolean, default=True),
        Column("timezone", String, default="UTC"),
        Column("last_run_at", DateTime(timezone=True)),
        Column("next_run_at", DateTime(timezone=True)),
        Column("deleted_at", DateTime(timezone=True), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}schedules_agent_id", "agent_id"),
        Index(
            f"ix_{prefix}schedules_next_run",
            "next_run_at",
            postgresql_where=Column("enabled") == True,  # noqa: E712
        ),
    )

    users = Table(
        f"{prefix}users",
        metadata,
        Column("user_id", String, primary_key=True),
        Column("display_name", String, nullable=True),
        Column("email", String, nullable=True),
        Column("metadata_json", JSON, nullable=False, server_default="{}"),
        Column("first_seen_at", DateTime(timezone=True)),
        Column("last_seen_at", DateTime(timezone=True)),
    )

    conversations = Table(
        f"{prefix}conversations",
        metadata,
        Column("conversation_id", String, primary_key=True),
        Column("agent_id", String, nullable=False),
        Column("user_id", String, nullable=True),
        Column("title", String, nullable=True),
        Column("summary", Text, nullable=True),
        Column("message_count", Integer, default=0),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True)),
        Column("ended_at", DateTime(timezone=True)),
        Index(f"ix_{prefix}conversations_user_agent", "user_id", "agent_id"),
        Index(f"ix_{prefix}conversations_user", "user_id"),
    )

    conversation_messages = Table(
        f"{prefix}conversation_messages",
        metadata,
        Column("message_id", String, primary_key=True),
        Column(
            "conversation_id",
            String,
            ForeignKey(f"{prefix}conversations.conversation_id"),
            nullable=False,
        ),
        Column("role", String, nullable=False),
        Column("content", Text, nullable=False),
        Column("metadata_json", JSON, server_default="{}"),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}conv_messages_conv_id", "conversation_id"),
    )

    memories = Table(
        f"{prefix}memories",
        metadata,
        Column("id", String, primary_key=True),
        Column("agent_id", String, nullable=False),
        Column("user_id", String, nullable=True),  # NULL = global agent memory
        Column("content", Text, nullable=False),
        Column("memory_type", String, nullable=False, default="semantic"),
        Column("source", String, nullable=False, default="manual"),
        Column("importance", Float, default=0.5),
        Column("access_count", Integer, default=0),
        Column("last_accessed_at", DateTime(timezone=True), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}memories_agent_user", "agent_id", "user_id"),
        Index(f"ix_{prefix}memories_agent_id", "agent_id"),
    )

    user_agent_configs = Table(
        f"{prefix}user_agent_configs",
        metadata,
        Column("user_id", String, nullable=False, primary_key=True),
        Column("agent_id", String, nullable=False, primary_key=True),
        Column("instructions", Text, nullable=True),
        Column("config_values", JSON, nullable=False, server_default="{}"),
        Column("encrypted_secrets", JSON, nullable=False, server_default="{}"),
        Column("setup_completed", Boolean, nullable=False, default=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}user_agent_configs_user_id", "user_id"),
        Index(f"ix_{prefix}user_agent_configs_agent_id", "agent_id"),
    )

    user_schedules = Table(
        f"{prefix}user_schedules",
        metadata,
        Column("id", String, primary_key=True),
        Column("user_id", String, nullable=False),
        Column("agent_id", String, nullable=False),
        Column("name", String, nullable=False),
        Column("cron_expr", String, nullable=False),
        Column("message", Text, nullable=False),
        Column("input", JSON),
        Column("enabled", Boolean, default=True),
        Column("timezone", String, default="UTC"),
        Column("notify", JSON, nullable=True),
        Column("last_run_at", DateTime(timezone=True)),
        Column("next_run_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Index(f"ix_{prefix}user_schedules_user_id", "user_id"),
        Index(f"ix_{prefix}user_schedules_user_agent", "user_id", "agent_id"),
    )

    return {
        "executions": executions,
        "execution_steps": execution_steps,
        "audit_log": audit_log,
        "schedules": schedules,
        "users": users,
        "conversations": conversations,
        "conversation_messages": conversation_messages,
        "memories": memories,
        "user_agent_configs": user_agent_configs,
        "user_schedules": user_schedules,
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

    mapper_registry.map_imperatively(
        UserProfile,
        tables["users"],
        properties={
            "metadata": tables["users"].c.metadata_json,
        },
    )

    mapper_registry.map_imperatively(
        ConversationRecord,
        tables["conversations"],
        properties={
            "messages": relationship(
                ConversationMessage,
                back_populates="conversation",
                cascade="all, delete-orphan",
            ),
        },
    )

    mapper_registry.map_imperatively(
        ConversationMessage,
        tables["conversation_messages"],
        properties={
            "metadata": tables["conversation_messages"].c.metadata_json,
            "conversation": relationship(ConversationRecord, back_populates="messages"),
        },
    )

    mapper_registry.map_imperatively(MemoryRecord, tables["memories"])

    mapper_registry.map_imperatively(UserAgentConfig, tables["user_agent_configs"])

    mapper_registry.map_imperatively(UserScheduleRecord, tables["user_schedules"])


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
        table_prefix: str = "",
    ) -> None:
        self._engine = engine
        self._metadata = metadata
        self._mapper_registry = mapper_registry
        self._tables = tables
        self._table_prefix = table_prefix
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
            ConversationRepository as ConvRepo,
        )
        from agent_gateway.persistence.backends.sql.repository import (
            ExecutionRepository as ExecRepo,
        )
        from agent_gateway.persistence.backends.sql.repository import (
            ScheduleRepository as SchedRepo,
        )
        from agent_gateway.persistence.backends.sql.repository import (
            UserAgentConfigRepository as UserAgentConfigRepo,
        )
        from agent_gateway.persistence.backends.sql.repository import (
            UserRepository as UserRepo,
        )
        from agent_gateway.persistence.backends.sql.repository import (
            UserScheduleRepository as UserSchedRepo,
        )

        self._execution_repo: ExecutionRepository = ExecRepo(self._session_factory)
        self._audit_repo: AuditRepository = AuditRepo(self._session_factory)
        self._schedule_repo: ScheduleRepository = SchedRepo(self._session_factory)
        self._user_repo: UserRepository = UserRepo(self._session_factory)
        self._conversation_repo: ConversationRepository = ConvRepo(self._session_factory)
        self._user_agent_config_repo: UserAgentConfigRepository = UserAgentConfigRepo(
            self._session_factory
        )
        self._user_schedule_repo: UserScheduleRepository = UserSchedRepo(self._session_factory)

    async def initialize(self) -> None:
        """Apply database migrations. Falls back to create_all for prefixed tables."""
        if self._table_prefix or self._metadata.schema:
            # Alembic migrations use hardcoded table names; use create_all for
            # prefixed tables or custom schemas
            async with self._engine.begin() as conn:
                await conn.run_sync(self._metadata.create_all)
            logger.info("Database tables initialized (prefix=%s)", self._table_prefix)
            return

        try:
            from agent_gateway.persistence.migrations.runner import run_upgrade

            async with self._engine.begin() as conn:
                await conn.run_sync(run_upgrade)
            logger.info("Database migrations applied")
        except Exception:
            logger.warning("Alembic migration failed, falling back to create_all", exc_info=True)
            async with self._engine.begin() as conn:
                await conn.run_sync(self._metadata.create_all)
            logger.info("Database tables initialized via create_all fallback")

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

    @property
    def schedule_repo(self) -> ScheduleRepository:
        return self._schedule_repo

    @property
    def user_repo(self) -> UserRepository:
        return self._user_repo

    @property
    def conversation_repo(self) -> ConversationRepository:
        return self._conversation_repo

    @property
    def user_agent_config_repo(self) -> UserAgentConfigRepository:
        return self._user_agent_config_repo

    @property
    def user_schedule_repo(self) -> UserScheduleRepository:
        return self._user_schedule_repo
