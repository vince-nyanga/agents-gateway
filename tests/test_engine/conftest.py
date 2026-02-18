"""Shared fixtures for engine tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_gateway.config import GatewayConfig
from agent_gateway.engine.executor import ExecutionEngine
from agent_gateway.engine.llm import LLMResponse
from agent_gateway.engine.models import ToolCall, ToolContext
from agent_gateway.hooks import HookRegistry
from agent_gateway.workspace.agent import AgentDefinition, AgentModelConfig
from agent_gateway.workspace.loader import WorkspaceState
from agent_gateway.workspace.registry import CodeTool, ResolvedTool, ToolRegistry


def make_agent(
    agent_id: str = "test-agent",
    skills: list[str] | None = None,
    tools: list[str] | None = None,
    model: AgentModelConfig | None = None,
) -> AgentDefinition:
    """Create a minimal agent definition for testing."""
    return AgentDefinition(
        id=agent_id,
        path=Path("/tmp/agents") / agent_id,
        agent_prompt="You are a test agent.",
        skills=skills or [],
        tools=tools or [],
        model=model or AgentModelConfig(),
    )


def make_workspace(
    agents: dict[str, AgentDefinition] | None = None,
) -> WorkspaceState:
    """Create a minimal workspace state for testing."""
    return WorkspaceState(
        path=Path("/tmp/workspace"),
        agents=agents or {},
        skills={},
        tools={},
        schedules=[],
        root_system_prompt="",
        root_soul_prompt="",
        warnings=[],
        errors=[],
    )


def make_llm_response(
    text: str | None = None,
    tool_calls: list[ToolCall] | None = None,
    model: str = "gpt-4o-mini",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> LLMResponse:
    """Create an LLM response for testing."""
    return LLMResponse(
        text=text,
        tool_calls=tool_calls or [],
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=0.001,
    )


def make_tool_call(
    name: str = "echo",
    arguments: dict[str, Any] | None = None,
    call_id: str = "call_1",
) -> ToolCall:
    """Create a tool call for testing."""
    return ToolCall(name=name, arguments=arguments or {}, call_id=call_id)


class MockLLMClient:
    """Mock LLM client that returns pre-configured responses."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    async def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._call_count >= len(self._responses):
            raise RuntimeError("No more mock responses configured")
        response = self._responses[self._call_count]
        self._call_count += 1
        return response

    def resolve_model_params(
        self, agent_model: AgentModelConfig | None
    ) -> tuple[str | None, float, int]:
        return None, 0.1, 4096

    async def close(self) -> None:
        pass


def make_engine(
    responses: list[LLMResponse],
    tools: list[ResolvedTool] | None = None,
    config: GatewayConfig | None = None,
    hooks: HookRegistry | None = None,
) -> tuple[ExecutionEngine, MockLLMClient, ToolRegistry]:
    """Create an engine with a mock LLM client for testing."""
    mock_llm = MockLLMClient(responses)
    cfg = config or GatewayConfig()
    registry = ToolRegistry()

    # Register tools
    if tools:
        for tool in tools:
            if tool.code_tool:
                registry.register_code_tool(tool.code_tool)

    engine = ExecutionEngine(
        llm_client=mock_llm,  # type: ignore[arg-type]
        tool_registry=registry,
        config=cfg,
        hooks=hooks,
    )
    return engine, mock_llm, registry


def make_resolved_tool(
    name: str = "echo",
    description: str = "Echo tool",
    allowed_agents: list[str] | None = None,
) -> ResolvedTool:
    """Create a resolved tool for testing."""

    async def _handler(**kwargs: Any) -> dict[str, Any]:
        return {"echo": kwargs}

    code_tool = CodeTool(
        name=name,
        description=description,
        fn=_handler,
        parameters_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        allowed_agents=allowed_agents,
    )

    return ResolvedTool(
        name=name,
        description=description,
        source="code",
        llm_declaration=code_tool.to_llm_declaration(),
        parameters_schema=code_tool.parameters_schema,
        allowed_agents=allowed_agents,
        code_tool=code_tool,
    )


async def simple_tool_executor(
    tool: ResolvedTool, arguments: dict[str, Any], context: ToolContext
) -> Any:
    """A simple tool executor that calls the code tool function."""
    if tool.code_tool:
        return await tool.code_tool.fn(**arguments)
    return {"error": "no handler"}
