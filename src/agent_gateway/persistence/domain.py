"""Plain domain dataclasses for persistence — zero ORM dependencies.

These types are the public interface for all persistence operations.
They are always importable from the core package without any optional extras.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


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
    session_id: str | None = None
    user_id: str | None = None
    schedule_id: str | None = None
    schedule_name: str | None = None
    parent_execution_id: str | None = None
    root_execution_id: str | None = None
    delegation_depth: int = 0
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
    instructions: str | None = None
    input: dict[str, Any] | None = None
    enabled: bool = True
    timezone: str = "UTC"
    source: Literal["workspace", "admin"] = "workspace"
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class UserProfile:
    """Persistent user profile extracted from auth claims."""

    user_id: str  # JWT sub claim or other identity
    display_name: str | None = None
    email: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass
class UserAgentConfig:
    """Per-user configuration for a personal agent."""

    user_id: str
    agent_id: str
    instructions: str | None = None
    config_values: dict[str, Any] = field(default_factory=dict)
    encrypted_secrets: dict[str, Any] = field(default_factory=dict)
    setup_completed: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class UserScheduleRecord:
    """Per-user schedule for personal agent invocations."""

    id: str
    user_id: str
    agent_id: str
    name: str
    cron_expr: str
    message: str
    instructions: str | None = None
    input: dict[str, Any] | None = None
    enabled: bool = True
    timezone: str = "UTC"
    notify: dict[str, Any] | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class NotificationDeliveryRecord:
    """Tracks notification delivery attempts and outcomes."""

    id: int | None = None  # auto-increment
    execution_id: str = ""
    agent_id: str = ""
    event_type: str = ""
    channel: str = ""
    target: str = ""  # sanitized — no query params on URLs
    status: str = "pending"  # delivered | failed
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None


@dataclass
class ConversationRecord:
    """A persisted conversation between a user and an agent."""

    conversation_id: str  # Same as session_id
    agent_id: str
    user_id: str | None = None  # NULL = shared/anonymous
    title: str | None = None
    summary: str | None = None
    message_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass
class ConversationMessage:
    """A single message within a conversation."""

    message_id: str
    conversation_id: str
    role: str  # user, assistant, system, tool
    content: str
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


@dataclass
class McpServerConfig:
    """Configuration for an MCP server connection. Persisted in DB."""

    id: str  # UUID
    name: str  # unique, slug-like: "my-github-server"
    transport: str  # "stdio" | "streamable_http"
    # Stdio fields
    command: str | None = None  # e.g. "python"
    args: list[str] | None = None  # e.g. ["-m", "my_mcp_server"]
    encrypted_env: str | None = None  # Fernet-encrypted JSON of env dict
    # HTTP fields
    url: str | None = None  # e.g. "http://localhost:8080/mcp"
    headers: dict[str, str] | None = None  # legacy plaintext headers (deprecated)
    encrypted_headers: str | None = None  # Fernet-encrypted JSON of headers dict
    # Auth (all sensitive values encrypted)
    encrypted_credentials: str | None = None  # Fernet-encrypted JSON of credentials dict
    # Metadata
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
