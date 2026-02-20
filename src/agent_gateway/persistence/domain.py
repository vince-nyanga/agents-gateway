"""Plain domain dataclasses for persistence — zero ORM dependencies.

These types are the public interface for all persistence operations.
They are always importable from the core package without any optional extras.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ExecutionRecord:
    """Tracks agent execution history."""

    id: str
    agent_id: str
    status: str = "queued"
    message: str = ""
    input: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    schedule_id: str | None = None
    schedule_name: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    steps: list[ExecutionStep] = field(default_factory=list)


@dataclass
class ExecutionStep:
    """Individual step within an execution (LLM call, tool call, tool result)."""

    execution_id: str
    step_type: str
    sequence: int
    id: int | None = None
    data: dict[str, Any] | None = None
    duration_ms: int = 0
    created_at: datetime | None = None


@dataclass
class AuditLogEntry:
    """Audit trail for security-relevant events."""

    event_type: str
    id: int | None = None
    actor: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at: datetime | None = None


@dataclass
class ScheduleRecord:
    """Persisted schedule state for cron-based agent invocations."""

    id: str
    agent_id: str
    name: str
    cron_expr: str
    message: str
    input: dict[str, Any] | None = None
    enabled: bool = True
    timezone: str = "UTC"
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None
