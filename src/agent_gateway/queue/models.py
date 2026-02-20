"""Data models for the execution queue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionJob:
    """A serialisable job for the execution queue.

    All fields are JSON-primitive types — no datetime objects, no nested
    Protocol instances. This ensures round-trip serialisation without
    custom encoders.
    """

    execution_id: str
    agent_id: str
    message: str
    input: dict[str, Any] | None = None
    timeout_ms: int | None = None
    output_schema: dict[str, Any] | None = None
    enqueued_at: str = ""  # ISO 8601 string
    retry_count: int = 0
    schedule_id: str | None = None

    def to_json(self) -> str:
        """Serialise to JSON string."""
        return json.dumps(
            {
                "execution_id": self.execution_id,
                "agent_id": self.agent_id,
                "message": self.message,
                "input": self.input,
                "timeout_ms": self.timeout_ms,
                "output_schema": self.output_schema,
                "enqueued_at": self.enqueued_at,
                "retry_count": self.retry_count,
                "schedule_id": self.schedule_id,
            }
        )

    @classmethod
    def from_json(cls, data: str) -> ExecutionJob:
        """Deserialise from JSON string."""
        parsed = json.loads(data)
        return cls(
            execution_id=parsed["execution_id"],
            agent_id=parsed["agent_id"],
            message=parsed["message"],
            input=parsed.get("input"),
            timeout_ms=parsed.get("timeout_ms"),
            output_schema=parsed.get("output_schema"),
            enqueued_at=parsed.get("enqueued_at", ""),
            retry_count=parsed.get("retry_count", 0),
            schedule_id=parsed.get("schedule_id"),
        )
