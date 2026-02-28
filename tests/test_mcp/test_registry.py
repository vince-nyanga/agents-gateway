"""Tests for ToolRegistry MCP tool registration and clearing."""

from __future__ import annotations

from agent_gateway.mcp.domain import McpToolInfo
from agent_gateway.workspace.registry import ToolRegistry


def _make_tool(server: str = "srv", name: str = "tool1") -> McpToolInfo:
    return McpToolInfo(
        server_name=server,
        name=name,
        description=f"{server}/{name}",
        input_schema={"type": "object"},
    )


class TestToolRegistryMcp:
    def test_register_mcp_tools(self) -> None:
        reg = ToolRegistry()
        tools = [_make_tool("s1", "t1"), _make_tool("s1", "t2")]
        reg.register_mcp_tools(tools, allowed_agents=["agent-a"])

        all_tools = reg.get_all()
        assert "s1__t1" in all_tools
        assert "s1__t2" in all_tools
        assert all_tools["s1__t1"].source == "mcp"
        assert all_tools["s1__t1"].allowed_agents == ["agent-a"]
        assert all_tools["s1__t1"].mcp_tool is not None
        assert all_tools["s1__t1"].mcp_tool.server_name == "s1"
        assert all_tools["s1__t1"].mcp_tool.tool_name == "t1"

    def test_register_mcp_tools_no_allowed_agents(self) -> None:
        reg = ToolRegistry()
        reg.register_mcp_tools([_make_tool()], allowed_agents=None)
        tool = reg.get("srv__tool1")
        assert tool is not None
        assert tool.allowed_agents is None

    def test_clear_all_mcp_tools(self) -> None:
        reg = ToolRegistry()
        reg.register_mcp_tools([_make_tool("s1", "t1"), _make_tool("s2", "t2")])
        assert len(reg.get_all()) == 2

        reg.clear_mcp_tools()
        assert len(reg.get_all()) == 0

    def test_clear_mcp_tools_by_server(self) -> None:
        reg = ToolRegistry()
        reg.register_mcp_tools([_make_tool("s1", "t1")])
        reg.register_mcp_tools([_make_tool("s2", "t2")])
        assert len(reg.get_all()) == 2

        reg.clear_mcp_tools(server_name="s1")
        all_tools = reg.get_all()
        assert len(all_tools) == 1
        assert "s2__t2" in all_tools

    def test_clear_mcp_tools_by_server_nonexistent(self) -> None:
        """Clearing tools for a server that doesn't exist is a no-op."""
        reg = ToolRegistry()
        reg.register_mcp_tools([_make_tool("s1", "t1")])
        reg.clear_mcp_tools(server_name="nonexistent")
        assert len(reg.get_all()) == 1

    def test_mcp_tools_overridden_by_code_tools(self) -> None:
        """Code tools should override MCP tools with the same name."""
        from agent_gateway.workspace.registry import CodeTool

        reg = ToolRegistry()
        reg.register_mcp_tools([_make_tool("s1", "overlap")])

        async def handler(**kwargs: object) -> str:
            return "code"

        code_tool = CodeTool(
            name="s1__overlap",
            description="Code override",
            fn=handler,
            parameters_schema={},
        )
        reg.register_code_tool(code_tool)

        resolved = reg.get("s1__overlap")
        assert resolved is not None
        assert resolved.source == "code"

    def test_invalidates_cache(self) -> None:
        reg = ToolRegistry()
        _ = reg.get_all()  # populate cache
        assert reg._resolved is not None

        reg.register_mcp_tools([_make_tool()])
        assert reg._resolved is None  # cache invalidated
