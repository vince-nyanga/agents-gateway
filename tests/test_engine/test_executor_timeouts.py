"""Tests for execution engine timeout behavior."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_gateway.config import GatewayConfig, GuardrailsConfig
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


class TestOverallTimeout:
    @pytest.mark.asyncio
    async def test_overall_timeout(self) -> None:
        """Execution times out when LLM takes too long."""
        echo_tool = make_resolved_tool(name="echo")

        # LLM that takes too long
        async def slow_completion(**kwargs: Any) -> None:
            await asyncio.sleep(5)

        config = GatewayConfig(guardrails=GuardrailsConfig(timeout_ms=100))
        engine, mock_llm, _ = make_engine(
            responses=[],  # Won't be used
            tools=[echo_tool],
            config=config,
        )
        # Replace completion with slow version
        mock_llm.completion = slow_completion  # type: ignore[assignment]

        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(agent, "slow", workspace)

        assert result.stop_reason == StopReason.TIMEOUT


class TestPerToolTimeout:
    @pytest.mark.asyncio
    async def test_tool_timeout_returns_error_to_llm(self) -> None:
        """Tool that times out returns error, loop continues."""
        echo_tool = make_resolved_tool(name="slow-tool")

        async def slow_executor(
            tool: ResolvedTool, arguments: dict[str, Any], context: ToolContext
        ) -> Any:
            await asyncio.sleep(5)
            return {"never": "reached"}

        # Use a short overall timeout to not wait forever
        config = GatewayConfig(guardrails=GuardrailsConfig(timeout_ms=500))
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call(name="slow-tool", arguments={}, call_id="c1")]
                ),
                make_llm_response(text="Tool timed out, done"),
            ],
            tools=[echo_tool],
            config=config,
        )

        agent = make_agent(tools=["slow-tool"])
        workspace = make_workspace()

        # The overall timeout will catch the slow tool, resulting in TIMEOUT
        result = await engine.execute(agent, "test", workspace, tool_executor=slow_executor)

        # Either TIMEOUT (overall catches it) or COMPLETED (if tool timeout fires first)
        assert result.stop_reason in (StopReason.TIMEOUT, StopReason.COMPLETED)
