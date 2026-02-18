"""Tests for tool runner dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_gateway.engine.models import ToolContext
from agent_gateway.tools.runner import ToolRunner
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
        "async def handle(arguments, context):\n"
        "    return {'handled': arguments}\n"
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
    runner = ToolRunner()
    tool = _make_code_tool()
    result = await runner.execute(tool, {"message": "hello"}, _make_context())
    assert result == {"echo": {"message": "hello"}}


async def test_dispatch_file_tool(tmp_path: Path) -> None:
    runner = ToolRunner()
    tool = _make_file_tool_with_handler(tmp_path)
    result = await runner.execute(tool, {"x": 1}, _make_context())
    assert result == {"handled": {"x": 1}}


async def test_dispatch_no_executor() -> None:
    runner = ToolRunner()
    tool = ResolvedTool(
        name="broken",
        description="No executor",
        source="code",
        llm_declaration={},
        parameters_schema={},
    )
    result = await runner.execute(tool, {}, _make_context())
    assert "error" in result


async def test_dispatch_file_tool_no_handler() -> None:
    runner = ToolRunner()
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
    result = await runner.execute(tool, {}, _make_context())
    assert "error" in result
