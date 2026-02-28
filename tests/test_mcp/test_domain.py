"""Tests for MCP domain types."""

from __future__ import annotations

from agent_gateway.mcp.domain import MCP_TOOL_SEPARATOR, McpToolInfo, McpToolRef


class TestMcpToolInfo:
    def test_namespaced_name(self) -> None:
        info = McpToolInfo(
            server_name="myserver",
            name="do_thing",
            description="Does a thing",
            input_schema={"type": "object"},
        )
        assert info.namespaced_name == f"myserver{MCP_TOOL_SEPARATOR}do_thing"
        assert info.namespaced_name == "myserver__do_thing"

    def test_separator_is_double_underscore(self) -> None:
        assert MCP_TOOL_SEPARATOR == "__"


class TestMcpToolRef:
    def test_fields(self) -> None:
        ref = McpToolRef(server_name="srv", tool_name="tool1")
        assert ref.server_name == "srv"
        assert ref.tool_name == "tool1"
