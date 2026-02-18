"""Integration test: execute_tool used as the tool_executor in ExecutionEngine."""

from __future__ import annotations

from typing import Any

import pytest

from agent_gateway.engine.models import StopReason, ToolCall
from agent_gateway.tools.runner import execute_tool
from agent_gateway.workspace.registry import CodeTool, ResolvedTool
from tests.test_engine.conftest import (
    make_agent,
    make_engine,
    make_llm_response,
    make_tool_call,
    make_workspace,
)


def _make_echo_tool() -> ResolvedTool:
    async def echo(**kwargs: Any) -> dict[str, Any]:
        return {"echo": kwargs}

    code = CodeTool(
        name="echo",
        description="Echo tool",
        fn=echo,
        parameters_schema={"type": "object", "properties": {"message": {"type": "string"}}},
    )
    return ResolvedTool(
        name="echo",
        description="Echo tool",
        source="code",
        llm_declaration=code.to_llm_declaration(),
        parameters_schema=code.parameters_schema,
        code_tool=code,
    )


class TestExecuteToolIntegration:
    @pytest.mark.asyncio
    async def test_single_tool_call(self) -> None:
        """execute_tool works as the ToolExecutorFn in ExecutionEngine."""
        tool = _make_echo_tool()
        engine, mock_llm, registry = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call("echo", {"message": "hello"})],
                ),
                make_llm_response(text="The echo returned: hello"),
            ],
            tools=[tool],
        )

        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(
            agent=agent,
            message="Echo hello",
            workspace=workspace,
            tool_executor=execute_tool,
        )

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == "The echo returned: hello"
        assert result.usage.tool_calls == 1

    @pytest.mark.asyncio
    async def test_multiple_tools(self) -> None:
        """execute_tool dispatches parallel tool calls to different code tools."""

        async def add(a: float = 0, b: float = 0, **kwargs: Any) -> dict[str, float]:
            return {"result": a + b}

        add_code = CodeTool(
            name="add",
            description="Add numbers",
            fn=add,
            parameters_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
            },
        )
        add_tool = ResolvedTool(
            name="add",
            description="Add numbers",
            source="code",
            llm_declaration=add_code.to_llm_declaration(),
            parameters_schema=add_code.parameters_schema,
            code_tool=add_code,
        )

        echo_tool = _make_echo_tool()

        engine, mock_llm, registry = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[
                        ToolCall(name="add", arguments={"a": 2, "b": 3}, call_id="call_1"),
                        ToolCall(name="echo", arguments={"message": "hi"}, call_id="call_2"),
                    ],
                ),
                make_llm_response(text="2+3=5 and echo says hi"),
            ],
            tools=[echo_tool, add_tool],
        )

        agent = make_agent(tools=["echo", "add"])
        workspace = make_workspace()

        result = await engine.execute(
            agent=agent,
            message="Add 2+3 and echo hi",
            workspace=workspace,
            tool_executor=execute_tool,
        )

        assert result.stop_reason == StopReason.COMPLETED
        assert result.usage.tool_calls == 2
