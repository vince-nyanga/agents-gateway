"""Tool runner — dispatches tool calls to the correct executor."""

from __future__ import annotations

import logging
from typing import Any

from agent_gateway.engine.models import ToolContext
from agent_gateway.tools.function import execute_code_tool, execute_function_tool
from agent_gateway.workspace.registry import ResolvedTool

logger = logging.getLogger(__name__)


class ToolRunner:
    """Dispatches tool calls to the correct executor.

    Code tools (@gw.tool) are called directly.
    File tools (handler.py) are dynamically imported and called.
    """

    async def execute(
        self,
        tool: ResolvedTool,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> Any:
        """Execute a tool call, dispatching to the correct executor.

        This is the ToolExecutorFn used by the execution engine.
        """
        if tool.source == "code" and tool.code_tool is not None:
            return await execute_code_tool(tool.code_tool, arguments, context)

        if tool.file_tool is not None:
            return await execute_function_tool(tool.file_tool, arguments, context)

        return {"error": "Tool has no executor"}
