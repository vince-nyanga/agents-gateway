"""Shared test fixtures and helpers for tool executor tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_gateway.engine.models import ToolContext
from agent_gateway.workspace.registry import CodeTool, ResolvedTool
from agent_gateway.workspace.tool import ToolDefinition


def make_context() -> ToolContext:
    """Create a ToolContext for testing."""
    return ToolContext(execution_id="exec_1", agent_id="test-agent")


def make_code_tool(name: str = "echo") -> ResolvedTool:
    """Create a ResolvedTool backed by a code tool that echoes its arguments."""

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


def make_file_tool_with_handler(tmp_path: Path) -> ResolvedTool:
    """Create a ResolvedTool backed by a file-based handler.py."""
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
