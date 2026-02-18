"""SQLAlchemy 2.0 async models for Agent Gateway persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


class ExecutionRecord(Base):
    """Tracks agent execution history."""

    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    steps: Mapped[list[ExecutionStep]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class ExecutionStep(Base):
    """Individual steps within an execution (LLM calls, tool calls, tool results)."""

    __tablename__ = "execution_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(
        String, ForeignKey("executions.id"), nullable=False, index=True
    )
    step_type: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    execution: Mapped[ExecutionRecord] = relationship(back_populates="steps")


class AuditLogEntry(Base):
    """Audit trail for security-relevant events."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str | None] = mapped_column(String, default=None)
    resource_type: Mapped[str | None] = mapped_column(String, default=None)
    resource_id: Mapped[str | None] = mapped_column(String, default=None)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, default=None)
    ip_address: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class ScheduleRecord(Base):
    """Persisted schedule state for cron-based agent invocations."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cron_expr: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String, default="UTC")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_schedules_next_run", "next_run_at", postgresql_where="enabled = TRUE"),
    )
