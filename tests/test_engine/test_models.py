"""Tests for execution engine data models."""

from __future__ import annotations

import pytest

from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
    ExecutionStatus,
    StopReason,
    ToolCall,
    ToolContext,
    ToolResult,
    UsageAccumulator,
)


class TestStopReason:
    def test_values(self) -> None:
        assert StopReason.COMPLETED.value == "completed"
        assert StopReason.MAX_ITERATIONS.value == "max_iterations"
        assert StopReason.MAX_TOOL_CALLS.value == "max_tool_calls"
        assert StopReason.TIMEOUT.value == "timeout"
        assert StopReason.CANCELLED.value == "cancelled"
        assert StopReason.ERROR.value == "error"

    def test_string_enum(self) -> None:
        assert str(StopReason.COMPLETED) == "completed"
        assert StopReason.COMPLETED == "completed"


class TestExecutionStatus:
    def test_all_states(self) -> None:
        assert len(ExecutionStatus) == 8
        assert ExecutionStatus.QUEUED.value == "queued"
        assert ExecutionStatus.APPROVAL_PENDING.value == "approval_pending"


class TestToolCall:
    def test_creation(self) -> None:
        tc = ToolCall(name="echo", arguments={"msg": "hi"}, call_id="call_1")
        assert tc.name == "echo"
        assert tc.arguments == {"msg": "hi"}
        assert tc.call_id == "call_1"


class TestToolResult:
    def test_success(self) -> None:
        tr = ToolResult(call_id="c1", name="echo", success=True, output={"echo": "hi"})
        assert tr.success
        assert tr.duration_ms == 0

    def test_failure(self) -> None:
        tr = ToolResult(
            call_id="c1", name="echo", success=False, output={"error": "boom"}, duration_ms=42
        )
        assert not tr.success
        assert tr.duration_ms == 42


class TestUsageAccumulator:
    def test_empty(self) -> None:
        u = UsageAccumulator()
        assert u.input_tokens == 0
        assert u.llm_calls == 0
        assert u.models_used == []

    def test_add_llm_usage(self) -> None:
        u = UsageAccumulator()
        u.add_llm_usage(model="gpt-4o", input_tokens=100, output_tokens=50, cost=0.001)
        u.add_llm_usage(model="gpt-4o", input_tokens=200, output_tokens=100, cost=0.002)
        assert u.input_tokens == 300
        assert u.output_tokens == 150
        assert u.cost_usd == pytest.approx(0.003)
        assert u.llm_calls == 2
        assert u.models_used == ["gpt-4o"]  # No duplicate

    def test_add_llm_usage_multiple_models(self) -> None:
        u = UsageAccumulator()
        u.add_llm_usage(model="gpt-4o", input_tokens=100)
        u.add_llm_usage(model="claude-3", input_tokens=100)
        assert u.models_used == ["gpt-4o", "claude-3"]

    def test_add_tool_call(self) -> None:
        u = UsageAccumulator()
        u.add_tool_call()
        u.add_tool_call()
        assert u.tool_calls == 2

    def test_to_dict(self) -> None:
        u = UsageAccumulator()
        u.add_llm_usage(model="gpt-4o", input_tokens=10, output_tokens=5, cost=0.0001234)
        u.add_tool_call()
        d = u.to_dict()
        assert d["input_tokens"] == 10
        assert d["output_tokens"] == 5
        assert d["cost_usd"] == 0.000123  # Rounded to 6 decimal places
        assert d["llm_calls"] == 1
        assert d["tool_calls"] == 1
        assert d["models_used"] == ["gpt-4o"]


class TestExecutionOptions:
    def test_defaults(self) -> None:
        opts = ExecutionOptions()
        assert opts.async_execution is False
        assert opts.timeout_ms is None
        assert opts.stream is False
        assert opts.output_schema is None


class TestExecutionResult:
    def test_completed(self) -> None:
        r = ExecutionResult(raw_text="Hello", stop_reason=StopReason.COMPLETED)
        assert r.output is None
        assert r.error is None

    def test_to_dict(self) -> None:
        r = ExecutionResult(
            output={"answer": 42},
            raw_text='{"answer": 42}',
            stop_reason=StopReason.COMPLETED,
        )
        d = r.to_dict()
        assert d["output"] == {"answer": 42}
        assert d["stop_reason"] == "completed"
        assert "error" not in d
        assert "validation_errors" not in d

    def test_to_dict_with_error(self) -> None:
        r = ExecutionResult(
            stop_reason=StopReason.ERROR, error="LLM failed", validation_errors=["bad json"]
        )
        d = r.to_dict()
        assert d["error"] == "LLM failed"
        assert d["validation_errors"] == ["bad json"]


class TestToolContext:
    def test_creation(self) -> None:
        ctx = ToolContext(execution_id="e1", agent_id="test-agent")
        assert ctx.execution_id == "e1"
        assert ctx.caller_identity is None
        assert ctx.metadata == {}


class TestExecutionHandle:
    def test_cancel(self) -> None:
        h = ExecutionHandle(execution_id="e1")
        assert not h.is_cancelled
        h.cancel()
        assert h.is_cancelled

    def test_execution_id(self) -> None:
        h = ExecutionHandle(execution_id="abc")
        assert h.execution_id == "abc"
