"""Tests for execution engine guardrails (max iterations, max tool calls)."""

from __future__ import annotations

import pytest

from agent_gateway.config import GatewayConfig, GuardrailsConfig
from agent_gateway.engine.models import StopReason
from tests.test_engine.conftest import (
    make_agent,
    make_engine,
    make_llm_response,
    make_resolved_tool,
    make_tool_call,
    make_workspace,
    simple_tool_executor,
)


class TestMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_hit(self) -> None:
        """Loop exhausts max_iterations → MAX_ITERATIONS."""
        echo_tool = make_resolved_tool(name="echo")
        config = GatewayConfig(guardrails=GuardrailsConfig(max_iterations=2, max_tool_calls=100))

        # Every response includes a tool call, so the loop never completes naturally
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[
                        make_tool_call(name="echo", arguments={"message": "1"}, call_id="c1"),
                    ]
                ),
                make_llm_response(
                    tool_calls=[
                        make_tool_call(name="echo", arguments={"message": "2"}, call_id="c2"),
                    ]
                ),
            ],
            tools=[echo_tool],
            config=config,
        )
        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "loop forever", workspace, tool_executor=simple_tool_executor
        )

        assert result.stop_reason == StopReason.MAX_ITERATIONS
        assert result.usage.llm_calls == 2


class TestMaxToolCalls:
    @pytest.mark.asyncio
    async def test_max_tool_calls_hit(self) -> None:
        """Total tool calls exceed limit → MAX_TOOL_CALLS."""
        echo_tool = make_resolved_tool(name="echo")
        config = GatewayConfig(guardrails=GuardrailsConfig(max_tool_calls=2, max_iterations=100))

        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[
                        make_tool_call(name="echo", arguments={"message": "1"}, call_id="c1"),
                    ]
                ),
                make_llm_response(
                    tool_calls=[
                        make_tool_call(name="echo", arguments={"message": "2"}, call_id="c2"),
                    ]
                ),
                # Would need a 3rd call but won't reach it
            ],
            tools=[echo_tool],
            config=config,
        )
        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "call tools", workspace, tool_executor=simple_tool_executor
        )

        assert result.stop_reason == StopReason.MAX_TOOL_CALLS
        assert result.usage.tool_calls == 2
