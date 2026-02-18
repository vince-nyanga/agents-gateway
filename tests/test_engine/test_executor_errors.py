"""Tests for execution engine error isolation."""

from __future__ import annotations

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
    simple_tool_executor,
)


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_to_llm(self) -> None:
        """LLM calls a tool that doesn't exist → error in tool result, loop continues."""
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call(name="nonexistent", arguments={}, call_id="c1")]
                ),
                make_llm_response(text="OK, that tool doesn't exist"),
            ],
        )
        agent = make_agent()
        workspace = make_workspace()

        result = await engine.execute(
            agent, "call nonexistent", workspace, tool_executor=simple_tool_executor
        )

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == "OK, that tool doesn't exist"


class TestToolPermissionDenied:
    @pytest.mark.asyncio
    async def test_tool_not_permitted_for_agent(self) -> None:
        """Tool exists but is restricted → error returned, loop continues."""
        restricted_tool = make_resolved_tool(
            name="restricted", allowed_agents=["other-agent"]
        )
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call(name="restricted", arguments={}, call_id="c1")]
                ),
                make_llm_response(text="Permission denied, moving on"),
            ],
            tools=[restricted_tool],
        )
        # The tool is registered but agent doesn't have access via resolve_for_agent
        # In practice, resolve_for_agent filters it out, so it appears as unknown
        agent = make_agent(tools=["restricted"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "call restricted", workspace, tool_executor=simple_tool_executor
        )

        assert result.stop_reason == StopReason.COMPLETED


class TestToolException:
    @pytest.mark.asyncio
    async def test_tool_raises_exception(self) -> None:
        """Tool raises exception → error returned to LLM, loop continues."""
        echo_tool = make_resolved_tool(name="failing-tool")

        async def failing_executor(
            tool: ResolvedTool, arguments: dict[str, Any], context: ToolContext
        ) -> Any:
            raise ValueError("Tool crashed!")

        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call(name="failing-tool", arguments={}, call_id="c1")]
                ),
                make_llm_response(text="Tool failed, but I handled it"),
            ],
            tools=[echo_tool],
        )
        agent = make_agent(tools=["failing-tool"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "test", workspace, tool_executor=failing_executor
        )

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == "Tool failed, but I handled it"


class TestOversizedResult:
    @pytest.mark.asyncio
    async def test_tool_result_truncated(self) -> None:
        """Tool result exceeding 32KB is truncated."""
        echo_tool = make_resolved_tool(name="big-tool")

        large_output = "x" * 40_000

        async def big_executor(
            tool: ResolvedTool, arguments: dict[str, Any], context: ToolContext
        ) -> Any:
            return large_output

        engine, mock_llm, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call(name="big-tool", arguments={}, call_id="c1")]
                ),
                make_llm_response(text="Got truncated result"),
            ],
            tools=[echo_tool],
        )
        agent = make_agent(tools=["big-tool"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "test", workspace, tool_executor=big_executor
        )

        assert result.stop_reason == StopReason.COMPLETED
        # Verify the tool result message was truncated
        tool_msg = mock_llm.calls[1]["messages"][-1]  # Last message before 2nd LLM call
        assert "[truncated: result exceeded 32KB limit]" in tool_msg["content"]


class TestNoToolExecutor:
    @pytest.mark.asyncio
    async def test_no_executor_configured(self) -> None:
        """When no tool executor is provided, tools return an error."""
        echo_tool = make_resolved_tool(name="echo")
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call(name="echo", arguments={}, call_id="c1")]
                ),
                make_llm_response(text="No executor"),
            ],
            tools=[echo_tool],
        )
        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        # No tool_executor passed
        result = await engine.execute(agent, "test", workspace)

        assert result.stop_reason == StopReason.COMPLETED
