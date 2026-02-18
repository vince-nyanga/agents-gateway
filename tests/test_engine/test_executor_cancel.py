"""Tests for execution engine cancellation."""

from __future__ import annotations

import pytest

from agent_gateway.engine.models import ExecutionHandle, StopReason
from tests.test_engine.conftest import (
    make_agent,
    make_engine,
    make_llm_response,
    make_resolved_tool,
    make_tool_call,
    make_workspace,
    simple_tool_executor,
)


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancel_before_execution(self) -> None:
        """Cancel event set before execution starts → CANCELLED immediately."""
        engine, _, _ = make_engine(responses=[make_llm_response(text="Should not reach this")])
        agent = make_agent()
        workspace = make_workspace()

        handle = ExecutionHandle(execution_id="e1")
        handle.cancel()

        result = await engine.execute(agent, "Hi", workspace, handle=handle)

        assert result.stop_reason == StopReason.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_between_iterations(self) -> None:
        """Cancel after first tool call → CANCELLED after tool completes."""
        echo_tool = make_resolved_tool(name="echo")
        handle = ExecutionHandle(execution_id="e1")

        call_count = 0
        original_responses = [
            make_llm_response(
                tool_calls=[make_tool_call(name="echo", arguments={"message": "1"}, call_id="c1")]
            ),
            make_llm_response(text="Should not reach"),
        ]

        engine, mock_llm, _ = make_engine(
            responses=original_responses,
            tools=[echo_tool],
        )

        # Wrap completion to cancel after first call
        original_completion = mock_llm.completion

        async def cancelling_completion(**kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            result = await original_completion(**kwargs)
            call_count += 1
            if call_count == 1:
                handle.cancel()
            return result

        mock_llm.completion = cancelling_completion  # type: ignore[assignment]

        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "test", workspace, handle=handle, tool_executor=simple_tool_executor
        )

        assert result.stop_reason == StopReason.CANCELLED
