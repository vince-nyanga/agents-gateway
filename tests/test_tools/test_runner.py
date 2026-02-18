"""Tests for tool runner dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_gateway.engine.models import ToolContext
from agent_gateway.tools.runner import execute_tool
from agent_gateway.workspace.registry import CodeTool, ResolvedTool
from agent_gateway.workspace.tool import ToolDefinition


def _make_context() -> ToolContext:
    return ToolContext(execution_id="exec_1", agent_id="test-agent")


def _make_code_tool(name: str = "echo") -> ResolvedTool:
    async def _handler(**kwargs: Any) -> dict[str, Any]:
        return {"echo": kwargs}

    code = CodeTool(
        name=name,
        description="Echo tool",
        fn=_handler,
        parameters_schema={"type": "object", "properties": {}},
    )
    return ResolvedTool(
        name=name,
        description="Echo tool",
        source="code",
        llm_declaration={},
        parameters_schema={},
        code_tool=code,
    )


def _make_file_tool_with_handler(tmp_path: Path) -> ResolvedTool:
    tool_dir = tmp_path / "test-tool"
    tool_dir.mkdir(exist_ok=True)
    handler = tool_dir / "handler.py"
    handler.write_text(
        "async def handle(arguments, context):\n    return {'handled': arguments}\n"
    )

    file_tool = ToolDefinition(
        id="test-tool",
        path=tool_dir,
        name="test-tool",
        description="A test tool",
        handler_path=handler,
    )
    return ResolvedTool(
        name="test-tool",
        description="A test tool",
        source="file",
        llm_declaration={},
        parameters_schema={},
        file_tool=file_tool,
    )


async def test_dispatch_code_tool() -> None:
    tool = _make_code_tool()
    result = await execute_tool(tool, {"message": "hello"}, _make_context())
    assert result == {"echo": {"message": "hello"}}


async def test_dispatch_file_tool(tmp_path: Path) -> None:
    tool = _make_file_tool_with_handler(tmp_path)
    result = await execute_tool(tool, {"x": 1}, _make_context())
    assert result == {"handled": {"x": 1}}


async def test_dispatch_no_executor_raises() -> None:
    tool = ResolvedTool(
        name="broken",
        description="No executor",
        source="code",
        llm_declaration={},
        parameters_schema={},
    )
    with pytest.raises(RuntimeError, match="has no executor"):
        await execute_tool(tool, {}, _make_context())


async def test_dispatch_file_tool_no_handler_raises() -> None:
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
        await execute_tool(tool, {}, _make_context())
