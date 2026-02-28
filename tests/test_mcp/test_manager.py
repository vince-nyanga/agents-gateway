"""Tests for McpConnectionManager."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_gateway.exceptions import McpToolExecutionError
from agent_gateway.mcp.domain import McpToolInfo
from agent_gateway.mcp.manager import (
    McpConnection,
    McpConnectionManager,
    _format_mcp_result,
)
from agent_gateway.persistence.domain import McpServerConfig


def _make_config(
    name: str = "test-server",
    transport: str = "stdio",
    **kwargs: Any,
) -> McpServerConfig:
    defaults: dict[str, Any] = {
        "id": "srv-1",
        "name": name,
        "transport": transport,
        "enabled": True,
    }
    if transport == "stdio":
        defaults.setdefault("command", "echo")
    elif transport == "streamable_http":
        defaults.setdefault("url", "http://localhost:8080/mcp")
    defaults.update(kwargs)
    return McpServerConfig(**defaults)


class TestMcpConnectionManager:
    def test_init_defaults(self) -> None:
        mgr = McpConnectionManager()
        assert mgr._connection_timeout_s == 10.0
        assert mgr._tool_call_timeout_s == 30.0

    def test_init_custom_timeouts(self) -> None:
        mgr = McpConnectionManager(connection_timeout_ms=5000, tool_call_timeout_ms=15000)
        assert mgr._connection_timeout_s == 5.0
        assert mgr._tool_call_timeout_s == 15.0

    def test_get_tools_empty(self) -> None:
        mgr = McpConnectionManager()
        assert mgr.get_tools("nonexistent") == []

    def test_get_all_tools_empty(self) -> None:
        mgr = McpConnectionManager()
        assert mgr.get_all_tools() == {}

    def test_is_connected_false_when_absent(self) -> None:
        mgr = McpConnectionManager()
        assert mgr.is_connected("nonexistent") is False

    def test_is_connected_with_live_task(self) -> None:
        mgr = McpConnectionManager()
        task = MagicMock()
        task.done.return_value = False
        conn = McpConnection(
            config=_make_config(),
            session=MagicMock(),
            tools=[],
            _background_task=task,
        )
        mgr._connections["test-server"] = conn
        assert mgr.is_connected("test-server") is True

    def test_is_connected_with_done_task(self) -> None:
        mgr = McpConnectionManager()
        task = MagicMock()
        task.done.return_value = True
        conn = McpConnection(
            config=_make_config(),
            session=MagicMock(),
            tools=[],
            _background_task=task,
        )
        mgr._connections["test-server"] = conn
        assert mgr.is_connected("test-server") is False

    def test_get_tools_returns_copy(self) -> None:
        mgr = McpConnectionManager()
        tool = McpToolInfo(server_name="s", name="t", description="d", input_schema={})
        conn = McpConnection(
            config=_make_config(),
            session=MagicMock(),
            tools=[tool],
        )
        mgr._connections["test-server"] = conn
        result = mgr.get_tools("test-server")
        assert len(result) == 1
        assert result is not conn.tools  # returns a copy

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self) -> None:
        mgr = McpConnectionManager()
        with pytest.raises(McpToolExecutionError, match="not connected"):
            await mgr.call_tool("no-server", "tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_dead_task(self) -> None:
        mgr = McpConnectionManager()
        task = MagicMock()
        task.done.return_value = True
        conn = McpConnection(
            config=_make_config(),
            session=MagicMock(),
            tools=[],
            _background_task=task,
        )
        mgr._connections["test-server"] = conn
        with pytest.raises(McpToolExecutionError, match="connection has been lost"):
            await mgr.call_tool("test-server", "tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        mgr = McpConnectionManager()
        task = MagicMock()
        task.done.return_value = False

        # Mock session.call_tool to return a result with text content
        @dataclass
        class TextContent:
            text: str

        @dataclass
        class CallToolResult:
            content: list[Any]

        mock_session = AsyncMock()
        mock_session.call_tool.return_value = CallToolResult(content=[TextContent(text="hello")])

        conn = McpConnection(
            config=_make_config(),
            session=mock_session,
            tools=[],
            _background_task=task,
        )
        mgr._connections["test-server"] = conn

        result = await mgr.call_tool("test-server", "my_tool", {"arg": "val"})
        assert result == "hello"
        mock_session.call_tool.assert_called_once_with("my_tool", arguments={"arg": "val"})

    @pytest.mark.asyncio
    async def test_call_tool_timeout(self) -> None:
        mgr = McpConnectionManager(tool_call_timeout_ms=100)
        task = MagicMock()
        task.done.return_value = False

        mock_session = AsyncMock()

        async def slow_call(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(10)

        mock_session.call_tool = slow_call

        conn = McpConnection(
            config=_make_config(),
            session=mock_session,
            tools=[],
            _background_task=task,
        )
        mgr._connections["test-server"] = conn

        with pytest.raises(McpToolExecutionError, match="timed out"):
            await mgr.call_tool("test-server", "slow_tool", {})

    @pytest.mark.asyncio
    async def test_connect_all_skips_disabled(self) -> None:
        mgr = McpConnectionManager()
        config = _make_config(enabled=False)
        with patch.object(mgr, "_connect_one") as mock_connect:
            await mgr.connect_all([config])
            mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_all_logs_and_skips_failures(self) -> None:
        mgr = McpConnectionManager()
        config = _make_config(enabled=True)
        with patch.object(mgr, "_connect_one", side_effect=Exception("boom")):
            # Should not raise
            await mgr.connect_all([config])
        assert "test-server" not in mgr._connections

    @pytest.mark.asyncio
    async def test_disconnect_all(self) -> None:
        mgr = McpConnectionManager()
        shutdown_event = asyncio.Event()

        async def _bg_task() -> None:
            await shutdown_event.wait()

        bg_task = asyncio.create_task(_bg_task())
        conn = McpConnection(
            config=_make_config(),
            session=MagicMock(),
            tools=[],
            _shutdown_event=shutdown_event,
            _background_task=bg_task,
        )
        mgr._connections["test-server"] = conn

        await mgr.disconnect_all()
        assert len(mgr._connections) == 0
        assert shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_disconnect_one(self) -> None:
        mgr = McpConnectionManager()
        shutdown_event = asyncio.Event()

        async def _bg_task() -> None:
            await shutdown_event.wait()

        bg_task = asyncio.create_task(_bg_task())
        conn = McpConnection(
            config=_make_config(),
            session=MagicMock(),
            tools=[],
            _shutdown_event=shutdown_event,
            _background_task=bg_task,
        )
        mgr._connections["test-server"] = conn

        await mgr.disconnect_one("test-server")
        assert "test-server" not in mgr._connections
        assert shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_disconnect_one_noop_for_unknown(self) -> None:
        mgr = McpConnectionManager()
        # Should not raise
        await mgr.disconnect_one("nonexistent")


class TestFormatMcpResult:
    def test_text_content(self) -> None:
        @dataclass
        class TextItem:
            text: str

        @dataclass
        class Result:
            content: list[Any]

        result = Result(content=[TextItem(text="hello"), TextItem(text="world")])
        assert _format_mcp_result(result) == "hello\nworld"

    def test_binary_content_with_mimetype(self) -> None:
        @dataclass
        class BinItem:
            data: bytes
            mimeType: str

        @dataclass
        class Result:
            content: list[Any]

        result = Result(content=[BinItem(data=b"x", mimeType="image/png")])
        assert _format_mcp_result(result) == "[binary content: image/png]"

    def test_binary_content_without_mimetype(self) -> None:
        """P3-1: getattr guard for mimeType."""

        @dataclass
        class BinItem:
            data: bytes

        @dataclass
        class Result:
            content: list[Any]

        result = Result(content=[BinItem(data=b"x")])
        assert _format_mcp_result(result) == "[binary content: unknown]"

    def test_fallback_to_str(self) -> None:
        @dataclass
        class WeirdItem:
            val: int

            def __str__(self) -> str:
                return f"weird-{self.val}"

        @dataclass
        class Result:
            content: list[Any]

        result = Result(content=[WeirdItem(val=42)])
        assert _format_mcp_result(result) == "weird-42"
