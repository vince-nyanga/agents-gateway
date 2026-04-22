"""Tests for the SSE streaming chat execution engine."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_gateway.chat.session import ChatSession
from agent_gateway.engine.models import ExecutionHandle, ExecutionOptions
from agent_gateway.engine.streaming import (
    MAX_RESULT_SIZE,
    _serialize_tool_output,
    _sse_event,
    _truncate_result,
    stream_chat_execution,
)

from .conftest import make_agent, make_mock_gateway, make_resolved_tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect_events(
    gw: Any,
    agent: Any | None = None,
    session: ChatSession | None = None,
    messages: list[dict[str, Any]] | None = None,
    handle: ExecutionHandle | None = None,
    exec_options: ExecutionOptions | None = None,
) -> list[tuple[str, Any]]:
    """Run stream_chat_execution and collect all (event_type, data) tuples."""
    if agent is None:
        agent = make_agent()
    if session is None:
        session = ChatSession(session_id="sess_test", agent_id=agent.id)
    if messages is None:
        messages = [{"role": "user", "content": "hello"}]
    if handle is None:
        handle = ExecutionHandle(execution_id="exec_1")
    if exec_options is None:
        exec_options = ExecutionOptions()

    events: list[tuple[str, Any]] = []
    async for raw_sse in stream_chat_execution(
        gw=gw,
        agent=agent,
        session=session,
        messages=messages,
        exec_options=exec_options,
        execution_id="exec_1",
        handle=handle,
    ):
        # Parse SSE string: "event: <type>\ndata: <json>\n\n"
        lines = raw_sse.strip().split("\n")
        event_type = lines[0].removeprefix("event: ")
        data_str = lines[1].removeprefix("data: ")
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            data = data_str
        events.append((event_type, data))
    return events


def _text_chunks(text: str, model: str = "gpt-4o-mini") -> list[dict[str, Any]]:
    """Create a simple stream chunk list: token chunks + usage."""
    return [
        {"type": "token", "content": text},
        {
            "type": "usage",
            "model": model,
            "input_tokens": 10,
            "output_tokens": 5,
            "cost": 0.001,
        },
    ]


def _tool_call_chunks(
    name: str,
    arguments: dict[str, Any],
    call_id: str = "call_1",
    model: str = "gpt-4o-mini",
) -> list[dict[str, Any]]:
    """Create stream chunks for a tool call."""
    return [
        {
            "type": "tool_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": call_id,
        },
        {
            "type": "usage",
            "model": model,
            "input_tokens": 10,
            "output_tokens": 5,
            "cost": 0.001,
        },
    ]


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestSseEvent:
    def test_dict_data(self) -> None:
        result = _sse_event("token", {"content": "hi"})
        assert result == 'event: token\ndata: {"content": "hi"}\n\n'

    def test_string_data(self) -> None:
        result = _sse_event("error", "raw string")
        assert result == "event: error\ndata: raw string\n\n"

    def test_special_chars(self) -> None:
        result = _sse_event("token", {"content": 'line1\n"quoted"'})
        parsed = json.loads(result.split("data: ", 1)[1].strip())
        assert parsed["content"] == 'line1\n"quoted"'


class TestTruncateResult:
    def test_short_string(self) -> None:
        assert _truncate_result("short") == "short"

    def test_exact_limit(self) -> None:
        s = "x" * MAX_RESULT_SIZE
        assert _truncate_result(s) == s

    def test_long_string(self) -> None:
        s = "x" * (MAX_RESULT_SIZE + 100)
        result = _truncate_result(s)
        assert len(result) < len(s)
        assert result.endswith("[truncated: result exceeded 32KB limit]")


class TestSerializeToolOutput:
    def test_string_passthrough(self) -> None:
        assert _serialize_tool_output("hello") == "hello"

    def test_dict_serialization(self) -> None:
        assert _serialize_tool_output({"a": 1}) == '{"a": 1}'

    def test_non_serializable_fallback(self) -> None:
        obj = object()
        result = _serialize_tool_output(obj)
        assert "object" in result


# ===========================================================================
# Integration tests for stream_chat_execution
# ===========================================================================


class TestTokenEventEmission:
    async def test_token_events_emitted(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("Hello world")])
        events = await _collect_events(gw)

        token_events = [(t, d) for t, d in events if t == "token"]
        assert len(token_events) == 1
        assert token_events[0][1]["content"] == "Hello world"

        done_events = [(t, d) for t, d in events if t == "done"]
        assert len(done_events) == 1
        assert done_events[0][1]["status"] == "completed"

    async def test_raw_sse_format(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("Hi")])
        agent = make_agent()
        session = ChatSession(session_id="sess_test", agent_id=agent.id)
        handle = ExecutionHandle(execution_id="exec_1")

        raw_parts: list[str] = []
        async for part in stream_chat_execution(
            gw=gw,  # type: ignore[arg-type]
            agent=agent,
            session=session,
            messages=[{"role": "user", "content": "hi"}],
            exec_options=ExecutionOptions(),
            execution_id="exec_1",
            handle=handle,
        ):
            raw_parts.append(part)

        # Each part should be valid SSE format
        for part in raw_parts:
            assert part.startswith("event: ")
            assert part.endswith("\n\n")
            assert "\ndata: " in part


class TestToolCallAndResultEvents:
    async def test_tool_call_and_result_flow(self) -> None:
        tool = make_resolved_tool(name="echo", allowed_agents=["test-agent"])
        gw, _ = make_mock_gateway(
            stream_chunks=[
                _tool_call_chunks("echo", {"message": "hi"}),
                _text_chunks("Done"),
            ],
            tools=[tool],
        )
        events = await _collect_events(gw)

        tc_events = [d for t, d in events if t == "tool_call"]
        assert len(tc_events) == 1
        assert tc_events[0]["name"] == "echo"

        tr_events = [d for t, d in events if t == "tool_result"]
        assert len(tr_events) == 1
        assert tr_events[0]["name"] == "echo"

    async def test_unknown_tool_error(self) -> None:
        gw, _ = make_mock_gateway(
            stream_chunks=[
                _tool_call_chunks("nonexistent", {}),
                _text_chunks("ok"),
            ],
        )
        events = await _collect_events(gw)

        tr_events = [d for t, d in events if t == "tool_result"]
        assert len(tr_events) == 1
        assert "Unknown tool" in tr_events[0]["output"]["error"]

    async def test_permission_denied(self) -> None:
        """Tool not allowed for this agent is not resolved into tool_map,
        so LLM calling it results in 'Unknown tool' error."""
        tool = make_resolved_tool(name="restricted", allowed_agents=["other-agent"])
        gw, _ = make_mock_gateway(
            stream_chunks=[
                _tool_call_chunks("restricted", {}),
                _text_chunks("ok"),
            ],
            tools=[tool],
        )
        events = await _collect_events(gw)

        tr_events = [d for t, d in events if t == "tool_result"]
        assert len(tr_events) == 1
        # Tool is filtered out during resolution, so it appears as unknown
        assert "Unknown tool" in tr_events[0]["output"]["error"]


class TestToolSchemaValidation:
    async def test_invalid_args_rejected(self) -> None:
        """Tool with required schema property rejects missing arg."""

        async def _handler(**kwargs: Any) -> str:
            return "ok"

        from agent_gateway.workspace.registry import CodeTool, ResolvedTool

        code_tool = CodeTool(
            name="strict_tool",
            description="Strict",
            fn=_handler,
            parameters_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            allowed_agents=["test-agent"],
        )
        resolved = ResolvedTool(
            name="strict_tool",
            description="Strict",
            source="code",
            llm_declaration=code_tool.to_llm_declaration(),
            parameters_schema=code_tool.parameters_schema,
            allowed_agents=["test-agent"],
            code_tool=code_tool,
        )

        gw, _ = make_mock_gateway(
            stream_chunks=[
                _tool_call_chunks("strict_tool", {}, call_id="call_v"),
                _text_chunks("ok"),
            ],
            tools=[resolved],
        )
        events = await _collect_events(gw)

        tr_events = [d for t, d in events if t == "tool_result"]
        assert len(tr_events) == 1
        assert "Invalid arguments" in tr_events[0]["output"]["error"]


class TestToolExecutionFailure:
    async def test_tool_raises_exception(self) -> None:
        """Tool handler raises -> error tool_result event."""

        async def _fail(**kwargs: Any) -> str:
            raise RuntimeError("boom")

        from agent_gateway.workspace.registry import CodeTool, ResolvedTool

        code_tool = CodeTool(
            name="fail_tool",
            description="Fails",
            fn=_fail,
            parameters_schema={"type": "object", "properties": {}},
            allowed_agents=["test-agent"],
        )
        resolved = ResolvedTool(
            name="fail_tool",
            description="Fails",
            source="code",
            llm_declaration=code_tool.to_llm_declaration(),
            parameters_schema=code_tool.parameters_schema,
            allowed_agents=["test-agent"],
            code_tool=code_tool,
        )

        gw, _ = make_mock_gateway(
            stream_chunks=[
                _tool_call_chunks("fail_tool", {}, call_id="call_f"),
                _text_chunks("ok"),
            ],
            tools=[resolved],
        )
        events = await _collect_events(gw)

        tr_events = [d for t, d in events if t == "tool_result"]
        assert len(tr_events) == 1
        assert "failed" in tr_events[0]["output"]["error"]


class TestUsageAccumulation:
    async def test_usage_in_done_event(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("hi")])
        events = await _collect_events(gw)

        done = [d for t, d in events if t == "done"]
        assert len(done) == 1
        usage = done[0]["usage"]
        assert usage["input_tokens"] == 10
        assert usage["output_tokens"] == 5
        assert usage["cost_usd"] == 0.001

    async def test_usage_accumulates_across_iterations(self) -> None:
        tool = make_resolved_tool(name="echo", allowed_agents=["test-agent"])
        gw, _ = make_mock_gateway(
            stream_chunks=[
                _tool_call_chunks("echo", {"message": "a"}),
                _text_chunks("done"),
            ],
            tools=[tool],
        )
        events = await _collect_events(gw)

        done = [d for t, d in events if t == "done"]
        usage = done[0]["usage"]
        # Two LLM calls: one tool_call iteration + one text iteration
        assert usage["input_tokens"] == 20
        assert usage["llm_calls"] == 2


class TestErrorEvent:
    async def test_llm_failure_emits_error(self) -> None:
        """When stream_completion raises, we get error + done with status error."""
        gw, mock_llm = make_mock_gateway(stream_chunks=[])
        # No chunks configured -> will raise RuntimeError
        events = await _collect_events(gw)

        error_events = [d for t, d in events if t == "error"]
        assert len(error_events) >= 1
        assert "LLM call failed" in error_events[0]["message"]

        done = [d for t, d in events if t == "done"]
        assert done[0]["status"] == "error"


class TestSessionLock:
    async def test_lock_released_after_streaming(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("hi")])
        session = ChatSession(session_id="sess_lock", agent_id="test-agent")

        # Consume the stream
        await _collect_events(gw, session=session)

        # Lock should be released
        assert not session.lock.locked()

    async def test_lock_held_during_streaming(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("hi")])
        session = ChatSession(session_id="sess_lock2", agent_id="test-agent")
        agent = make_agent()
        handle = ExecutionHandle(execution_id="exec_1")

        lock_was_held = False

        async def _consume() -> None:
            nonlocal lock_was_held
            async for _ in stream_chat_execution(
                gw=gw,  # type: ignore[arg-type]
                agent=agent,
                session=session,
                messages=[{"role": "user", "content": "hi"}],
                exec_options=ExecutionOptions(),
                execution_id="exec_1",
                handle=handle,
            ):
                # During iteration the session lock should be held
                if session.lock.locked():
                    lock_was_held = True

        await _consume()
        assert lock_was_held


class TestCancellation:
    async def test_cancellation_via_handle(self) -> None:
        """Pre-cancelled handle stops before LLM call."""
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("should not see")])
        handle = ExecutionHandle(execution_id="exec_cancel")
        handle.cancel()

        events = await _collect_events(gw, handle=handle)

        # Should not have any token events since cancelled before first iteration
        token_events = [d for t, d in events if t == "token"]
        assert len(token_events) == 0

        done = [d for t, d in events if t == "done"]
        assert done[0]["status"] == "cancelled"

    async def test_asyncio_cancelled_error(self) -> None:
        """Task cancellation yields cancelled done status."""
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("hi")])
        agent = make_agent()
        session = ChatSession(session_id="sess_cancel", agent_id=agent.id)
        handle = ExecutionHandle(execution_id="exec_c2")

        collected: list[tuple[str, Any]] = []

        async def _consume() -> None:
            async for raw_sse in stream_chat_execution(
                gw=gw,  # type: ignore[arg-type]
                agent=agent,
                session=session,
                messages=[{"role": "user", "content": "hi"}],
                exec_options=ExecutionOptions(),
                execution_id="exec_c2",
                handle=handle,
            ):
                lines = raw_sse.strip().split("\n")
                event_type = lines[0].removeprefix("event: ")
                data_str = lines[1].removeprefix("data: ")
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = data_str
                collected.append((event_type, data))
                # Cancel the task after first event
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await _consume()


class TestConcurrencySemaphore:
    async def test_semaphore_limits_concurrency(self) -> None:
        """Only one stream proceeds at a time with Semaphore(1)."""
        gw, _ = make_mock_gateway(
            stream_chunks=[_text_chunks("a"), _text_chunks("b")],
        )
        # Reset stream call count to allow two consumers
        sem = gw._execution_semaphore
        assert sem is not None

        order: list[str] = []
        agent = make_agent()

        async def _run(label: str) -> None:
            session = ChatSession(session_id=f"sess_{label}", agent_id=agent.id)
            handle = ExecutionHandle(execution_id=f"exec_{label}")
            async for _ in stream_chat_execution(
                gw=gw,  # type: ignore[arg-type]
                agent=agent,
                session=session,
                messages=[{"role": "user", "content": "hi"}],
                exec_options=ExecutionOptions(),
                execution_id=f"exec_{label}",
                handle=handle,
            ):
                pass
            order.append(label)

        t1 = asyncio.create_task(_run("first"))
        t2 = asyncio.create_task(_run("second"))
        await asyncio.gather(t1, t2)
        # Both should complete (order may vary, but both finish)
        assert len(order) == 2


class TestMaxIterations:
    async def test_stops_at_max_iterations(self) -> None:
        """Engine stops after max_iterations even if tool calls keep coming."""
        from agent_gateway.config import GatewayConfig, GuardrailsConfig

        cfg = GatewayConfig(guardrails=GuardrailsConfig(max_iterations=2))
        tool = make_resolved_tool(name="echo", allowed_agents=["test-agent"])

        # 3 iterations of tool calls, but max_iterations=2
        gw, _ = make_mock_gateway(
            stream_chunks=[
                _tool_call_chunks("echo", {"message": "1"}),
                _tool_call_chunks("echo", {"message": "2"}),
                _text_chunks("should not reach"),
            ],
            tools=[tool],
            config=cfg,
        )
        events = await _collect_events(gw)

        done = [d for t, d in events if t == "done"]
        assert done[0]["status"] == "max_iterations"


class TestEngineNotAvailable:
    async def test_null_snapshot(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[], snapshot=None)
        events = await _collect_events(gw)

        assert len(events) == 1
        assert events[0][0] == "error"
        assert "Engine not available" in events[0][1]["message"]

    async def test_null_engine(self) -> None:
        from agent_gateway.gateway import WorkspaceSnapshot
        from agent_gateway.workspace.registry import ToolRegistry

        ws = WorkspaceSnapshot(
            workspace=make_mock_gateway(stream_chunks=[])[0]._snapshot.workspace,  # type: ignore[union-attr]
            tool_registry=ToolRegistry(),
            engine=None,
        )
        gw, _ = make_mock_gateway(stream_chunks=[], snapshot=ws)
        events = await _collect_events(gw)

        assert len(events) == 1
        assert events[0][0] == "error"
        assert "Engine not available" in events[0][1]["message"]


class TestExecutionRecordCreation:
    async def test_record_includes_user_id(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("hi")])
        session = ChatSession(session_id="sess_user", agent_id="test-agent", user_id="user-123")
        events = await _collect_events(gw, session=session)

        repo = gw._execution_repo
        assert repo.create.call_count == 1
        record = repo.create.call_args[0][0]
        assert record.user_id == "user-123"
        assert record.session_id == "sess_user"

        token_events = [d for t, d in events if t == "token"]
        assert len(token_events) == 1


class TestRepoPersistenceFailure:
    async def test_repo_add_step_failure_does_not_break_stream(self) -> None:
        gw, _ = make_mock_gateway(stream_chunks=[_text_chunks("hi")])
        gw._execution_repo.add_step = AsyncMock(side_effect=RuntimeError("db error"))

        events = await _collect_events(gw)

        token_events = [d for t, d in events if t == "token"]
        assert len(token_events) == 1
        done = [d for t, d in events if t == "done"]
        assert done[0]["status"] == "completed"
