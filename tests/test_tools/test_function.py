"""Tests for function tool executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_gateway.engine.models import ToolContext
from agent_gateway.tools.function import (
    execute_code_tool,
    execute_function_tool,
    load_handler,
)
from agent_gateway.workspace.registry import CodeTool
from agent_gateway.workspace.tool import ToolDefinition


def _make_context() -> ToolContext:
    return ToolContext(execution_id="exec_1", agent_id="test-agent")


# --- Code tool tests ---


class TestExecuteCodeTool:
    async def test_async_function(self) -> None:
        async def echo(**kwargs: Any) -> dict[str, Any]:
            return {"echo": kwargs}

        tool = CodeTool(
            name="echo",
            description="Echo",
            fn=echo,
            parameters_schema={},
        )
        result = await execute_code_tool(tool, {"msg": "hi"}, _make_context())
        assert result == {"echo": {"msg": "hi"}}

    async def test_sync_function(self) -> None:
        def add(a: float = 0, b: float = 0, **kwargs: Any) -> dict[str, float]:
            return {"result": a + b}

        tool = CodeTool(name="add", description="Add", fn=add, parameters_schema={})
        result = await execute_code_tool(tool, {"a": 2, "b": 3}, _make_context())
        assert result == {"result": 5}

    async def test_context_injection(self) -> None:
        async def with_ctx(context: ToolContext, **kwargs: Any) -> dict[str, Any]:
            return {"agent": context.agent_id, "exec": context.execution_id}

        tool = CodeTool(name="ctx", description="Context", fn=with_ctx, parameters_schema={})
        ctx = _make_context()
        result = await execute_code_tool(tool, {}, ctx)
        assert result == {"agent": "test-agent", "exec": "exec_1"}

    async def test_exception_propagates(self) -> None:
        async def broken(**kwargs: Any) -> dict[str, Any]:
            raise ValueError("boom")

        tool = CodeTool(name="broken", description="Broken", fn=broken, parameters_schema={})
        with pytest.raises(ValueError, match="boom"):
            await execute_code_tool(tool, {}, _make_context())


# --- File-based function tool tests ---


class TestExecuteFunctionTool:
    async def test_async_handler(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "async-tool"
        tool_dir.mkdir()
        (tool_dir / "handler.py").write_text(
            "async def handle(arguments, context):\n"
            "    return {'got': arguments}\n"
        )

        tool = ToolDefinition(
            id="async-tool",
            path=tool_dir,
            name="async-tool",
            description="Async tool",
            handler_path=tool_dir / "handler.py",
        )
        result = await execute_function_tool(tool, {"x": 42}, _make_context())
        assert result == {"got": {"x": 42}}

    async def test_sync_handler(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "sync-tool"
        tool_dir.mkdir()
        (tool_dir / "handler.py").write_text(
            "def handle(arguments, context):\n"
            "    return {'sync': True, 'args': arguments}\n"
        )

        tool = ToolDefinition(
            id="sync-tool",
            path=tool_dir,
            name="sync-tool",
            description="Sync tool",
            handler_path=tool_dir / "handler.py",
        )
        result = await execute_function_tool(tool, {"a": 1}, _make_context())
        assert result == {"sync": True, "args": {"a": 1}}

    async def test_no_handler_path(self) -> None:
        tool = ToolDefinition(
            id="no-handler",
            path=Path("/tmp"),
            name="no-handler",
            description="No handler",
        )
        result = await execute_function_tool(tool, {}, _make_context())
        assert "error" in result

    async def test_handler_exception(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "err-tool"
        tool_dir.mkdir()
        (tool_dir / "handler.py").write_text(
            "async def handle(arguments, context):\n"
            "    raise RuntimeError('handler error')\n"
        )

        tool = ToolDefinition(
            id="err-tool",
            path=tool_dir,
            name="err-tool",
            description="Error tool",
            handler_path=tool_dir / "handler.py",
        )
        with pytest.raises(RuntimeError, match="handler error"):
            await execute_function_tool(tool, {}, _make_context())


# --- load_handler tests ---


class TestLoadHandler:
    def test_load_valid_handler(self, tmp_path: Path) -> None:
        handler = tmp_path / "handler.py"
        handler.write_text("def handle(args, ctx): return args")

        fn = load_handler(handler, "test")
        assert fn is not None
        assert callable(fn)

    def test_load_missing_handle_function(self, tmp_path: Path) -> None:
        handler = tmp_path / "handler.py"
        handler.write_text("def something_else(): pass")

        fn = load_handler(handler, "test")
        assert fn is None

    def test_load_import_error(self, tmp_path: Path) -> None:
        handler = tmp_path / "handler.py"
        handler.write_text("import nonexistent_module_xyz")

        fn = load_handler(handler, "test")
        assert fn is None

    def test_load_nonexistent_file(self) -> None:
        fn = load_handler(Path("/nonexistent/handler.py"), "test")
        assert fn is None
