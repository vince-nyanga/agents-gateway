"""Tests for the unified tool registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_gateway.workspace.registry import CodeTool, ResolvedTool, ToolRegistry
from agent_gateway.workspace.tool import ToolDefinition, ToolParameter


def _make_file_tool(
    name: str = "echo",
    description: str = "Echo back",
    permissions: dict[str, Any] | None = None,
) -> ToolDefinition:
    """Create a minimal ToolDefinition for testing."""
    return ToolDefinition(
        id=name,
        path=Path(f"/fake/{name}"),
        name=name,
        description=description,
        parameters=[
            ToolParameter(name="message", type="string", description="The message", required=True)
        ],
        permissions=permissions or {},
    )


def _make_code_tool(
    name: str = "add",
    description: str = "Add numbers",
    allowed_agents: list[str] | None = None,
) -> CodeTool:
    """Create a minimal CodeTool for testing."""

    async def dummy(a: float, b: float) -> dict:  # type: ignore[type-arg]
        return {"result": a + b}

    return CodeTool(
        name=name,
        description=description,
        fn=dummy,
        parameters_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "a"},
                "b": {"type": "number", "description": "b"},
            },
            "required": ["a", "b"],
        },
        allowed_agents=allowed_agents,
    )


class TestCodeToolDeclaration:
    def test_to_llm_declaration(self) -> None:
        tool = _make_code_tool()
        decl = tool.to_llm_declaration()
        assert decl["type"] == "function"
        assert decl["function"]["name"] == "add"
        assert decl["function"]["description"] == "Add numbers"
        assert "properties" in decl["function"]["parameters"]


class TestResolvedTool:
    def test_allows_agent_when_none(self) -> None:
        tool = ResolvedTool(
            name="t",
            description="d",
            source="code",
            llm_declaration={},
            parameters_schema={},
            allowed_agents=None,
        )
        assert tool.allows_agent("any-agent") is True

    def test_allows_agent_when_listed(self) -> None:
        tool = ResolvedTool(
            name="t",
            description="d",
            source="code",
            llm_declaration={},
            parameters_schema={},
            allowed_agents=["agent-a", "agent-b"],
        )
        assert tool.allows_agent("agent-a") is True
        assert tool.allows_agent("agent-c") is False


class TestToolRegistry:
    def test_register_and_get_file_tool(self) -> None:
        registry = ToolRegistry()
        tool = _make_file_tool()
        registry.register_file_tool(tool)

        resolved = registry.get("echo")
        assert resolved is not None
        assert resolved.name == "echo"
        assert resolved.source == "file"
        assert resolved.file_tool is tool

    def test_register_and_get_code_tool(self) -> None:
        registry = ToolRegistry()
        tool = _make_code_tool()
        registry.register_code_tool(tool)

        resolved = registry.get("add")
        assert resolved is not None
        assert resolved.name == "add"
        assert resolved.source == "code"
        assert resolved.code_tool is tool

    def test_code_tool_overrides_file_tool(self) -> None:
        registry = ToolRegistry()
        file_tool = _make_file_tool(name="echo", description="File version")
        code_tool = _make_code_tool(name="echo", description="Code version")

        registry.register_file_tool(file_tool)
        registry.register_code_tool(code_tool)

        resolved = registry.get("echo")
        assert resolved is not None
        assert resolved.source == "code"
        assert resolved.description == "Code version"

    def test_get_all(self) -> None:
        registry = ToolRegistry()
        registry.register_file_tool(_make_file_tool(name="echo"))
        registry.register_code_tool(_make_code_tool(name="add"))

        all_tools = registry.get_all()
        assert len(all_tools) == 2
        assert "echo" in all_tools
        assert "add" in all_tools

    def test_get_nonexistent_returns_none(self) -> None:
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_register_file_tools_bulk(self) -> None:
        registry = ToolRegistry()
        tools = {
            "echo": _make_file_tool(name="echo"),
            "greet": _make_file_tool(name="greet"),
        }
        registry.register_file_tools(tools)
        assert registry.get("echo") is not None
        assert registry.get("greet") is not None

    def test_cache_invalidated_on_register(self) -> None:
        registry = ToolRegistry()
        registry.register_file_tool(_make_file_tool(name="echo"))
        _ = registry.get_all()  # Populate cache

        registry.register_code_tool(_make_code_tool(name="add"))
        all_tools = registry.get_all()
        assert len(all_tools) == 2


class TestResolveForAgent:
    def test_resolve_direct_tools(self) -> None:
        registry = ToolRegistry()
        registry.register_file_tool(_make_file_tool(name="echo"))
        registry.register_code_tool(_make_code_tool(name="add"))

        resolved = registry.resolve_for_agent(
            agent_id="assistant",
            skill_tool_names=[],
            direct_tool_names=["echo", "add"],
        )
        names = [t.name for t in resolved]
        assert "echo" in names
        assert "add" in names

    def test_resolve_skill_tools(self) -> None:
        registry = ToolRegistry()
        registry.register_file_tool(_make_file_tool(name="echo"))

        resolved = registry.resolve_for_agent(
            agent_id="assistant",
            skill_tool_names=["echo"],
            direct_tool_names=[],
        )
        assert len(resolved) == 1
        assert resolved[0].name == "echo"

    def test_deduplicates_skill_and_direct(self) -> None:
        registry = ToolRegistry()
        registry.register_file_tool(_make_file_tool(name="echo"))

        resolved = registry.resolve_for_agent(
            agent_id="assistant",
            skill_tool_names=["echo"],
            direct_tool_names=["echo"],
        )
        assert len(resolved) == 1

    def test_filters_by_allowed_agents(self) -> None:
        registry = ToolRegistry()
        registry.register_code_tool(_make_code_tool(name="secret", allowed_agents=["admin-agent"]))

        resolved = registry.resolve_for_agent(
            agent_id="assistant",
            skill_tool_names=[],
            direct_tool_names=["secret"],
        )
        assert len(resolved) == 0

    def test_allowed_agent_passes(self) -> None:
        registry = ToolRegistry()
        registry.register_code_tool(_make_code_tool(name="secret", allowed_agents=["admin-agent"]))

        resolved = registry.resolve_for_agent(
            agent_id="admin-agent",
            skill_tool_names=[],
            direct_tool_names=["secret"],
        )
        assert len(resolved) == 1

    def test_missing_tool_skipped_with_warning(self) -> None:
        registry = ToolRegistry()
        resolved = registry.resolve_for_agent(
            agent_id="assistant",
            skill_tool_names=[],
            direct_tool_names=["nonexistent"],
        )
        assert len(resolved) == 0

    def test_file_tool_permissions(self) -> None:
        registry = ToolRegistry()
        tool = _make_file_tool(
            name="restricted",
            permissions={"allowed_agents": ["special-agent"], "require_approval": True},
        )
        registry.register_file_tool(tool)

        resolved = registry.get("restricted")
        assert resolved is not None
        assert resolved.allowed_agents == ["special-agent"]
        assert resolved.require_approval is True
        assert resolved.allows_agent("special-agent") is True
        assert resolved.allows_agent("other") is False


class TestLlmDeclarations:
    def test_to_llm_declarations(self) -> None:
        registry = ToolRegistry()
        registry.register_file_tool(_make_file_tool(name="echo"))
        registry.register_code_tool(_make_code_tool(name="add"))

        tools = registry.resolve_for_agent(
            agent_id="assistant",
            skill_tool_names=[],
            direct_tool_names=["echo", "add"],
        )
        declarations = registry.to_llm_declarations(tools)
        assert len(declarations) == 2
        for decl in declarations:
            assert decl["type"] == "function"
            assert "name" in decl["function"]
            assert "description" in decl["function"]
            assert "parameters" in decl["function"]
