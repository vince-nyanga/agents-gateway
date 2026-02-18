"""Tests for the core execution engine loop."""

from __future__ import annotations

from typing import Any

import pytest

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


class TestSimpleCompletion:
    @pytest.mark.asyncio
    async def test_text_response_no_tools(self) -> None:
        """LLM returns text with no tool calls → COMPLETED."""
        engine, mock_llm, _ = make_engine(responses=[make_llm_response(text="Hello, world!")])
        agent = make_agent()
        workspace = make_workspace()

        result = await engine.execute(agent, "Hi", workspace)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == "Hello, world!"
        assert result.usage.llm_calls == 1

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        """LLM returns empty text → COMPLETED with empty text."""
        engine, _, _ = make_engine(responses=[make_llm_response(text=None)])
        agent = make_agent()
        workspace = make_workspace()

        result = await engine.execute(agent, "Hi", workspace)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == ""


class TestToolCalling:
    @pytest.mark.asyncio
    async def test_single_tool_call(self) -> None:
        """LLM calls a tool, gets result, returns text."""
        echo_tool = make_resolved_tool(name="echo")
        engine, mock_llm, _ = make_engine(
            responses=[
                make_llm_response(
                    tool_calls=[make_tool_call(name="echo", arguments={"message": "hi"})]
                ),
                make_llm_response(text="The echo result was: hi"),
            ],
            tools=[echo_tool],
        )
        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "Echo hi", workspace, tool_executor=simple_tool_executor
        )

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == "The echo result was: hi"
        assert result.usage.llm_calls == 2
        assert result.usage.tool_calls == 1

    @pytest.mark.asyncio
    async def test_multi_iteration_loop(self) -> None:
        """LLM calls tools across 3 iterations before completing."""
        echo_tool = make_resolved_tool(name="echo")
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
                make_llm_response(
                    tool_calls=[
                        make_tool_call(name="echo", arguments={"message": "3"}, call_id="c3"),
                    ]
                ),
                make_llm_response(text="Done after 3 tool calls"),
            ],
            tools=[echo_tool],
        )
        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(
            agent, "Do three things", workspace, tool_executor=simple_tool_executor
        )

        assert result.stop_reason == StopReason.COMPLETED
        assert result.usage.llm_calls == 4
        assert result.usage.tool_calls == 3

    @pytest.mark.asyncio
    async def test_text_with_tool_calls(self) -> None:
        """LLM returns text AND tool calls — tool calls are processed, text preserved."""
        echo_tool = make_resolved_tool(name="echo")
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(
                    text="Let me call echo",
                    tool_calls=[make_tool_call(name="echo", arguments={"message": "hi"})],
                ),
                make_llm_response(text="Final answer"),
            ],
            tools=[echo_tool],
        )
        agent = make_agent(tools=["echo"])
        workspace = make_workspace()

        result = await engine.execute(agent, "test", workspace, tool_executor=simple_tool_executor)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == "Final answer"


class TestLLMError:
    @pytest.mark.asyncio
    async def test_llm_call_fails(self) -> None:
        """LLM call raises exception → ERROR stop reason."""

        class FailingLLM:
            async def completion(self, **kwargs: Any) -> None:
                raise RuntimeError("API down")

            def resolve_model_params(self, _: Any) -> tuple[None, float, int]:
                return None, 0.1, 4096

        from agent_gateway.config import GatewayConfig
        from agent_gateway.engine.executor import ExecutionEngine
        from agent_gateway.workspace.registry import ToolRegistry

        engine = ExecutionEngine(
            llm_client=FailingLLM(),  # type: ignore[arg-type]
            tool_registry=ToolRegistry(),
            config=GatewayConfig(),
        )
        agent = make_agent()
        workspace = make_workspace()

        result = await engine.execute(agent, "Hi", workspace)

        assert result.stop_reason == StopReason.ERROR
        assert result.error == "LLM call failed"
