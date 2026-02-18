"""Data models for the execution engine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StopReason(StrEnum):
    """Why an execution stopped."""

    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    MAX_TOOL_CALLS = "max_tool_calls"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ERROR = "error"


class ExecutionStatus(StrEnum):
    """Execution state machine states."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    name: str
    arguments: dict[str, Any]
    call_id: str


@dataclass
class ToolResult:
    """The result of executing a tool."""

    call_id: str
    name: str
    success: bool
    output: Any
    duration_ms: int = 0


@dataclass
class UsageAccumulator:
    """Tracks token usage, cost, and call counts across an execution."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    models_used: list[str] = field(default_factory=list)

    def add_llm_usage(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Record usage from an LLM call."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost
        self.llm_calls += 1
        if model not in self.models_used:
            self.models_used.append(model)

    def add_tool_call(self) -> None:
        """Record a tool call."""
        self.tool_calls += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "models_used": list(self.models_used),
        }


@dataclass
class ExecutionOptions:
    """Options parsed from an invocation request."""

    async_execution: bool = False
    timeout_ms: int | None = None
    output_schema: dict[str, Any] | None = None


@dataclass
class ExecutionResult:
    """The final result of an agent execution."""

    output: Any = None
    raw_text: str = ""
    stop_reason: StopReason = StopReason.COMPLETED
    usage: UsageAccumulator = field(default_factory=UsageAccumulator)
    error: str | None = None
    validation_errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses."""
        result: dict[str, Any] = {
            "output": self.output,
            "raw_text": self.raw_text,
            "stop_reason": self.stop_reason.value,
            "usage": self.usage.to_dict(),
        }
        if self.error:
            result["error"] = self.error
        if self.validation_errors:
            result["validation_errors"] = self.validation_errors
        return result


@dataclass
class ToolContext:
    """Context passed to tool handlers during execution."""

    execution_id: str
    agent_id: str
    caller_identity: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionHandle:
    """Handle for controlling a running execution (cancellation)."""

    def __init__(self, execution_id: str) -> None:
        self.execution_id = execution_id
        self._cancel_event = asyncio.Event()

    def cancel(self) -> None:
        """Signal the execution to cancel."""
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancel_event.is_set()
