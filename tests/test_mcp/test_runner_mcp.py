"""Tests for MCP tool dispatch in the tool runner."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent_gateway.engine.models import ToolContext
from agent_gateway.mcp.domain import McpToolRef
from agent_gateway.tools.runner import execute_mcp_tool, execute_tool
from agent_gateway.workspace.registry import ResolvedTool


def _make_mcp_resolved_tool(server: str = "srv", tool: str = "my_tool") -> ResolvedTool:
    return ResolvedTool(
        name=f"{server}__{tool}",
        description="An MCP tool",
        source="mcp",
        llm_declaration={},
        parameters_schema={},
        mcp_tool=McpToolRef(server_name=server, tool_name=tool),
    )


def _make_context(mcp_manager: object | None = None) -> ToolContext:
    return ToolContext(
        execution_id="exec-1",
        agent_id="test-agent",
        mcp_manager=mcp_manager,  # type: ignore[arg-type]
    )


class TestExecuteMcpTool:
    @pytest.mark.asyncio
    async def test_dispatch_to_mcp(self) -> None:
        """execute_tool dispatches MCP tools to execute_mcp_tool."""
        mock_mgr = AsyncMock()
        mock_mgr.call_tool.return_value = "mcp_result"

        tool = _make_mcp_resolved_tool()
        ctx = _make_context(mcp_manager=mock_mgr)

        result = await execute_tool(tool, {"key": "val"}, ctx)
        assert result == "mcp_result"
        mock_mgr.call_tool.assert_called_once_with("srv", "my_tool", {"key": "val"})

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_no_manager(self) -> None:
        """execute_mcp_tool raises when mcp_manager is None."""
        from agent_gateway.exceptions import McpToolExecutionError

        ref = McpToolRef(server_name="srv", tool_name="t")
        ctx = _make_context(mcp_manager=None)

        with pytest.raises(McpToolExecutionError, match="not available"):
            await execute_mcp_tool(ref, {}, ctx)
