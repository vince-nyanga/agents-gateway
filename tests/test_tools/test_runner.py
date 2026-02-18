"""Tests for tool runner dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_gateway.tools.runner import execute_tool
from agent_gateway.workspace.registry import ResolvedTool
from agent_gateway.workspace.tool import ToolDefinition
from tests.test_tools.conftest import make_code_tool, make_context, make_file_tool_with_handler


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_dispatch_code_tool(self) -> None:
        """Code tool is dispatched to execute_code_tool."""
        tool = make_code_tool()
        result = await execute_tool(tool, {"message": "hello"}, make_context())
        assert result == {"echo": {"message": "hello"}}

    @pytest.mark.asyncio
    async def test_dispatch_file_tool(self, tmp_path: Path) -> None:
        """File tool with handler.py is dispatched to execute_function_tool."""
        tool = make_file_tool_with_handler(tmp_path)
        result = await execute_tool(tool, {"x": 1}, make_context())
        assert result == {"handled": {"x": 1}}

    @pytest.mark.asyncio
    async def test_dispatch_no_executor_raises(self) -> None:
        """Tool with no code_tool or file_tool raises RuntimeError."""
        tool = ResolvedTool(
            name="broken",
            description="No executor",
            source="code",
            llm_declaration={},
            parameters_schema={},
        )
        with pytest.raises(RuntimeError, match="has no executor"):
            await execute_tool(tool, {}, make_context())

    @pytest.mark.asyncio
    async def test_dispatch_file_tool_no_handler_raises(self) -> None:
        """File tool without handler_path raises RuntimeError."""
        file_tool = ToolDefinition(
            id="no-handler",
            path=Path("/tmp/no-handler"),
            name="no-handler",
            description="No handler",
        )
        tool = ResolvedTool(
            name="no-handler",
            description="No handler",
            source="file",
            llm_declaration={},
            parameters_schema={},
            file_tool=file_tool,
        )
        with pytest.raises(RuntimeError, match="has no handler.py"):
            await execute_tool(tool, {}, make_context())
