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
from tests.test_tools.conftest import make_context


class TestExecuteCodeTool:
    @pytest.mark.asyncio
    async def test_async_function(self) -> None:
        """Async @gw.tool function is awaited and returns result."""

        async def echo(**kwargs: Any) -> dict[str, Any]:
            return {"echo": kwargs}

        tool = CodeTool(
            name="echo",
            description="Echo",
            fn=echo,
            parameters_schema={},
        )
        result = await execute_code_tool(tool, {"msg": "hi"}, make_context())
        assert result == {"echo": {"msg": "hi"}}

    @pytest.mark.asyncio
    async def test_sync_function(self) -> None:
        """Sync @gw.tool function is run via asyncio.to_thread."""

        def add(a: float = 0, b: float = 0, **kwargs: Any) -> dict[str, float]:
            return {"result": a + b}

        tool = CodeTool(name="add", description="Add", fn=add, parameters_schema={})
        result = await execute_code_tool(tool, {"a": 2, "b": 3}, make_context())
        assert result == {"result": 5}

    @pytest.mark.asyncio
    async def test_context_injection(self) -> None:
        """ToolContext is injected when function signature accepts 'context'."""

        async def with_ctx(context: ToolContext, **kwargs: Any) -> dict[str, Any]:
            return {"agent": context.agent_id, "exec": context.execution_id}

        tool = CodeTool(name="ctx", description="Context", fn=with_ctx, parameters_schema={})
        ctx = make_context()
        result = await execute_code_tool(tool, {}, ctx)
        assert result == {"agent": "test-agent", "exec": "exec_1"}

    @pytest.mark.asyncio
    async def test_exception_propagates(self) -> None:
        """Exceptions from @gw.tool functions propagate to caller."""

        async def broken(**kwargs: Any) -> dict[str, Any]:
            raise ValueError("boom")

        tool = CodeTool(name="broken", description="Broken", fn=broken, parameters_schema={})
        with pytest.raises(ValueError, match="boom"):
            await execute_code_tool(tool, {}, make_context())

    @pytest.mark.asyncio
    async def test_filters_unexpected_kwargs(self) -> None:
        """Extra arguments from the LLM are filtered out for functions without **kwargs."""

        async def strict(a: int, b: int) -> dict[str, int]:
            return {"sum": a + b}

        tool = CodeTool(name="strict", description="Strict", fn=strict, parameters_schema={})
        result = await execute_code_tool(tool, {"a": 1, "b": 2, "c": 99}, make_context())
        assert result == {"sum": 3}

    @pytest.mark.asyncio
    async def test_passes_all_kwargs_when_var_keyword(self) -> None:
        """Functions with **kwargs receive all arguments."""

        async def flexible(**kwargs: Any) -> dict[str, Any]:
            return kwargs

        tool = CodeTool(name="flex", description="Flex", fn=flexible, parameters_schema={})
        result = await execute_code_tool(tool, {"a": 1, "extra": "yes"}, make_context())
        assert result == {"a": 1, "extra": "yes"}


class TestExecuteFunctionTool:
    @pytest.mark.asyncio
    async def test_async_handler(self, tmp_path: Path) -> None:
        """Async handler.py handle() function is awaited."""
        tool_dir = tmp_path / "async-tool"
        tool_dir.mkdir()
        (tool_dir / "handler.py").write_text(
            "async def handle(arguments, context):\n    return {'got': arguments}\n"
        )

        tool = ToolDefinition(
            id="async-tool",
            path=tool_dir,
            name="async-tool",
            description="Async tool",
            handler_path=tool_dir / "handler.py",
        )
        result = await execute_function_tool(tool, {"x": 42}, make_context())
        assert result == {"got": {"x": 42}}

    @pytest.mark.asyncio
    async def test_sync_handler(self, tmp_path: Path) -> None:
        """Sync handler.py handle() function is run via asyncio.to_thread."""
        tool_dir = tmp_path / "sync-tool"
        tool_dir.mkdir()
        (tool_dir / "handler.py").write_text(
            "def handle(arguments, context):\n    return {'sync': True, 'args': arguments}\n"
        )

        tool = ToolDefinition(
            id="sync-tool",
            path=tool_dir,
            name="sync-tool",
            description="Sync tool",
            handler_path=tool_dir / "handler.py",
        )
        result = await execute_function_tool(tool, {"a": 1}, make_context())
        assert result == {"sync": True, "args": {"a": 1}}

    @pytest.mark.asyncio
    async def test_no_handler_path_raises(self) -> None:
        """Missing handler_path raises RuntimeError."""
        tool = ToolDefinition(
            id="no-handler",
            path=Path("/tmp"),
            name="no-handler",
            description="No handler",
        )
        with pytest.raises(RuntimeError, match="has no handler.py"):
            await execute_function_tool(tool, {}, make_context())

    @pytest.mark.asyncio
    async def test_broken_handler_raises(self, tmp_path: Path) -> None:
        """Handler that fails to import raises RuntimeError."""
        tool_dir = tmp_path / "bad-tool"
        tool_dir.mkdir()
        (tool_dir / "handler.py").write_text("import nonexistent_module_xyz\n")

        tool = ToolDefinition(
            id="bad-tool",
            path=tool_dir,
            name="bad-tool",
            description="Bad tool",
            handler_path=tool_dir / "handler.py",
        )
        with pytest.raises(RuntimeError, match="could not be loaded"):
            await execute_function_tool(tool, {}, make_context())

    @pytest.mark.asyncio
    async def test_handler_exception_propagates(self, tmp_path: Path) -> None:
        """Exceptions from handler.py propagate to caller."""
        tool_dir = tmp_path / "err-tool"
        tool_dir.mkdir()
        (tool_dir / "handler.py").write_text(
            "async def handle(arguments, context):\n    raise RuntimeError('handler error')\n"
        )

        tool = ToolDefinition(
            id="err-tool",
            path=tool_dir,
            name="err-tool",
            description="Error tool",
            handler_path=tool_dir / "handler.py",
        )
        with pytest.raises(RuntimeError, match="handler error"):
            await execute_function_tool(tool, {}, make_context())


class TestLoadHandler:
    def test_load_valid_handler(self, tmp_path: Path) -> None:
        """Valid handler.py with handle() function loads successfully."""
        handler = tmp_path / "handler.py"
        handler.write_text("def handle(args, ctx): return args")

        fn = load_handler(handler, "test")
        assert fn is not None
        assert callable(fn)

    def test_load_missing_handle_function(self, tmp_path: Path) -> None:
        """handler.py without handle() returns None."""
        handler = tmp_path / "handler.py"
        handler.write_text("def something_else(): pass")

        fn = load_handler(handler, "test")
        assert fn is None

    def test_load_import_error(self, tmp_path: Path) -> None:
        """handler.py that fails to import returns None."""
        handler = tmp_path / "handler.py"
        handler.write_text("import nonexistent_module_xyz")

        fn = load_handler(handler, "test")
        assert fn is None

    def test_load_nonexistent_file(self) -> None:
        """Nonexistent handler path returns None."""
        fn = load_handler(Path("/nonexistent/handler.py"), "test")
        assert fn is None
