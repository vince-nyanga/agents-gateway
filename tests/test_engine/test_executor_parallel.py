"""Tests for parallel tool execution in the execution engine."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_gateway.engine.models import StopReason, ToolContext
from agent_gateway.workspace.registry import ResolvedTool
from tests.test_engine.conftest import (
    make_agent,
    make_engine,
    make_llm_response,
    make_resolved_tool,
    make_tool_call,
    make_workspace,
)


class TestParallelToolExecution:
    @pytest.mark.asyncio
    async def test_multiple_tool_calls_execute_concurrently(self) -> None:
        """3 parallel tool calls all execute and complete."""
        echo_tool = make_resolved_tool(name="echo")
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[
                        make_tool_call(name="echo", arguments={"message": "a"}, call_id="c1"),
                        make_tool_call(name="echo", arguments={"message": "b"}, call_id="c2"),
                        make_tool_call(name="echo", arguments={"message": "c"}, call_id="c3"),
                    ]
                ),
                make_llm_response(text="All 3 done"),
            ],
            tools=[echo_tool],
        )
        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        execution_order: list[str] = []

        async def tracking_executor(
            tool: ResolvedTool, arguments: dict[str, Any], context: ToolContext
        ) -> Any:
            msg = arguments.get("message", "")
            execution_order.append(f"start:{msg}")
            await asyncio.sleep(0.01)  # Small delay to allow interleaving
            execution_order.append(f"end:{msg}")
            return {"echo": msg}

        result = await engine.execute(agent, "test", workspace, tool_executor=tracking_executor)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.usage.tool_calls == 3
        # All 3 should have started before any ended (concurrent)
        assert len(execution_order) == 6

    @pytest.mark.asyncio
    async def test_one_of_three_fails(self) -> None:
        """1 of 3 parallel tools fails → other 2 succeed, error for failing one."""
        echo_tool = make_resolved_tool(name="echo")
        fail_tool = make_resolved_tool(name="fail")

        async def mixed_executor(
            tool: ResolvedTool, arguments: dict[str, Any], context: ToolContext
        ) -> Any:
            if tool.name == "fail":
                raise ValueError("Tool crashed!")
            return {"echo": arguments.get("message", "")}

        engine, mock_llm, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[
                        make_tool_call(name="echo", arguments={"message": "a"}, call_id="c1"),
                        make_tool_call(name="fail", arguments={}, call_id="c2"),
                        make_tool_call(name="echo", arguments={"message": "c"}, call_id="c3"),
                    ]
                ),
                make_llm_response(text="Handled mixed results"),
            ],
            tools=[echo_tool, fail_tool],
        )
        agent = make_agent(tools=["echo", "fail"])
        workspace = make_workspace()

        result = await engine.execute(agent, "test", workspace, tool_executor=mixed_executor)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.usage.tool_calls == 3  # All counted

        # Verify the messages to the LLM include the error for the failing tool
        second_call_messages = mock_llm.calls[1]["messages"]
        tool_results = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_results) == 3

        # Find the error result
        error_results = [m for m in tool_results if "error" in m.get("content", "").lower()]
        assert len(error_results) == 1
