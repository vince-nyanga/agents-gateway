"""Tool runner — dispatches tool calls to the correct executor."""

from __future__ import annotations

from typing import Any

from agent_gateway.engine.models import ToolContext
from agent_gateway.tools.function import execute_code_tool, execute_function_tool
from agent_gateway.workspace.registry import ResolvedTool


async def execute_tool(
    tool: ResolvedTool,
    arguments: dict[str, Any],
    context: ToolContext,
) -> Any:
    """Execute a tool call, dispatching to the correct executor.

    Code tools (@gw.tool) are called directly.
    MCP tools are proxied to remote MCP servers via McpConnectionManager.
    File tools (handler.py) are dynamically imported and called.
    This satisfies the ToolExecutorFn signature used by the execution engine.
    """
    if tool.source == "code" and tool.code_tool is not None:
        return await execute_code_tool(tool.code_tool, arguments, context)

    if tool.source == "mcp" and tool.mcp_tool is not None:
        return await execute_mcp_tool(tool.mcp_tool, arguments, context)

    if tool.file_tool is not None:
        return await execute_function_tool(tool.file_tool, arguments, context)

    raise RuntimeError(f"Tool '{tool.name}' has no executor")


async def execute_mcp_tool(
    ref: Any,
    arguments: dict[str, Any],
    context: ToolContext,
) -> Any:
    """Execute a tool on a remote MCP server via the connection manager."""
    from agent_gateway.exceptions import McpToolExecutionError

    if context.mcp_manager is None:
        raise McpToolExecutionError(
            "MCP connection manager not available",
            server_name=ref.server_name,
            tool_name=ref.tool_name,
        )
    return await context.mcp_manager.call_tool(ref.server_name, ref.tool_name, arguments)
