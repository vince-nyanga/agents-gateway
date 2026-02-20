"""Notification domain models — plain dataclasses with zero optional-dependency imports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NotificationEvent:
    """Immutable event fired when an execution reaches a terminal state."""

    type: str  # execution.completed | execution.failed | execution.timeout
    execution_id: str
    agent_id: str
    status: str
    message: str  # the original user message
    result: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int = 0
    input: dict[str, Any] | None = None


@dataclass(frozen=True)
class NotificationTarget:
    """A single notification destination parsed from agent CONFIG.md.

    For Slack:
      - target: "#channel-name"
      - template: optional custom Block Kit template name

    For Webhook (two modes):
      - target: "crm-integration"  -> references a globally registered endpoint
      - url: "https://..."         -> inline endpoint, no global registration needed
    """

    channel: str  # "slack" | "webhook"
    target: str = ""  # Slack channel or global webhook name
    template: str | None = None  # Slack Block Kit template name
    url: str | None = None  # Inline webhook URL (per-agent)
    payload_template: str | None = None  # Inline webhook Jinja2 payload (per-agent)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for queue transport. Secrets are never serialized."""
        return {
            "channel": self.channel,
            "target": self.target,
            "template": self.template,
            "url": self.url,
            "payload_template": self.payload_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotificationTarget:
        return cls(
            channel=data["channel"],
            target=data.get("target", ""),
            template=data.get("template"),
            url=data.get("url"),
            payload_template=data.get("payload_template"),
        )


@dataclass
class AgentNotificationConfig:
    """Per-agent notification rules, parsed from CONFIG.md frontmatter."""

    on_complete: list[NotificationTarget] = field(default_factory=list)
    on_error: list[NotificationTarget] = field(default_factory=list)
    on_timeout: list[NotificationTarget] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "on_complete": [t.to_dict() for t in self.on_complete],
            "on_error": [t.to_dict() for t in self.on_error],
            "on_timeout": [t.to_dict() for t in self.on_timeout],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentNotificationConfig:
        return cls(
            on_complete=[NotificationTarget.from_dict(t) for t in data.get("on_complete", [])],
            on_error=[NotificationTarget.from_dict(t) for t in data.get("on_error", [])],
            on_timeout=[NotificationTarget.from_dict(t) for t in data.get("on_timeout", [])],
        )


@dataclass(frozen=True)
class NotificationJob:
    """A serialisable job for the notification queue.

    All fields are JSON-primitive types — no datetime objects, no nested
    Protocol instances. This ensures round-trip serialisation without
    custom encoders.
    """

    job_id: str
    execution_id: str
    agent_id: str
    status: str
    message: str
    config: dict[str, Any]  # serialised AgentNotificationConfig
    result: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    duration_ms: int = 0
    input: dict[str, Any] | None = None
    enqueued_at: str = ""  # ISO 8601 string

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "execution_id": self.execution_id,
                "agent_id": self.agent_id,
                "status": self.status,
                "message": self.message,
                "config": self.config,
                "result": self.result,
                "error": self.error,
                "usage": self.usage,
                "duration_ms": self.duration_ms,
                "input": self.input,
                "enqueued_at": self.enqueued_at,
            }
        )

    @classmethod
    def from_json(cls, data: str) -> NotificationJob:
        parsed = json.loads(data)
        return cls(
            job_id=parsed["job_id"],
            execution_id=parsed["execution_id"],
            agent_id=parsed["agent_id"],
            status=parsed["status"],
            message=parsed["message"],
            config=parsed["config"],
            result=parsed.get("result"),
            error=parsed.get("error"),
            usage=parsed.get("usage"),
            duration_ms=parsed.get("duration_ms", 0),
            input=parsed.get("input"),
            enqueued_at=parsed.get("enqueued_at", ""),
        )


def build_notification_job(
    *,
    job_id: str,
    execution_id: str,
    agent_id: str,
    status: str,
    message: str,
    config: AgentNotificationConfig,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    usage: dict[str, Any] | None = None,
    duration_ms: int = 0,
    input: dict[str, Any] | None = None,
    enqueued_at: str = "",
) -> NotificationJob:
    """Build a NotificationJob from execution result data."""
    return NotificationJob(
        job_id=job_id,
        execution_id=execution_id,
        agent_id=agent_id,
        status=status,
        message=message,
        config=config.to_dict(),
        result=result,
        error=error,
        usage=usage,
        duration_ms=duration_ms,
        input=input,
        enqueued_at=enqueued_at,
    )


_EVENT_TYPE_MAP: dict[str, str] = {
    "completed": "execution.completed",
    "failed": "execution.failed",
    "timeout": "execution.timeout",
    "error": "execution.failed",
    "cancelled": "execution.failed",
}


def build_notification_event(
    execution_id: str,
    agent_id: str,
    status: str,
    message: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    usage: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    duration_ms: int = 0,
    input: dict[str, Any] | None = None,
) -> NotificationEvent:
    """Build a NotificationEvent from execution result data."""
    event_type = _EVENT_TYPE_MAP.get(status, f"execution.{status}")

    return NotificationEvent(
        type=event_type,
        execution_id=execution_id,
        agent_id=agent_id,
        status=status,
        message=message,
        result=result,
        error=error,
        usage=usage,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        input=input,
    )
