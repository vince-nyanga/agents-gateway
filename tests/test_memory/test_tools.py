"""Tests for memory tools (recall, save, forget)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_gateway.config import MemoryConfig
from agent_gateway.engine.models import ToolContext
from agent_gateway.memory.backends.file import FileMemoryBackend
from agent_gateway.memory.manager import MemoryManager
from agent_gateway.memory.tools import make_memory_tools


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "agents" / "test-agent").mkdir(parents=True)
    return tmp_path


@pytest.fixture
async def manager(workspace: Path) -> MemoryManager:
    backend = FileMemoryBackend(workspace)
    await backend.initialize()
    return MemoryManager(
        backend=backend,
        llm_client=AsyncMock(),
        config=MemoryConfig(enabled=True),
    )


@pytest.fixture
def tools(manager: MemoryManager) -> dict:
    tool_list = make_memory_tools(manager)
    return {t["name"]: t for t in tool_list}


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(execution_id="exec-1", agent_id="test-agent", metadata={})


class TestMakeMemoryTools:
    def test_returns_three_tools(self, tools: dict) -> None:
        assert len(tools) == 3
        assert "memory_recall" in tools
        assert "memory_save" in tools
        assert "memory_forget" in tools

    def test_tools_have_parameters(self, tools: dict) -> None:
        for tool in tools.values():
            assert "parameters" in tool
            assert tool["parameters"]["type"] == "object"


class TestMemorySaveTool:
    async def test_save_returns_id(self, tools: dict, context: ToolContext) -> None:
        save_fn = tools["memory_save"]["func"]
        result = await save_fn(content="user prefers dark mode", context=context)
        assert "id" in result
        assert result["status"] == "saved"

    async def test_save_custom_type(self, tools: dict, context: ToolContext) -> None:
        save_fn = tools["memory_save"]["func"]
        result = await save_fn(
            content="always run tests first",
            memory_type="procedural",
            importance=0.9,
            context=context,
        )
        assert result["status"] == "saved"

    async def test_save_no_context_returns_error(self, tools: dict) -> None:
        save_fn = tools["memory_save"]["func"]
        result = await save_fn(content="test")
        assert "error" in result


class TestMemoryRecallTool:
    async def test_recall_finds_saved_memory(self, tools: dict, context: ToolContext) -> None:
        save_fn = tools["memory_save"]["func"]
        recall_fn = tools["memory_recall"]["func"]

        await save_fn(content="user prefers dark mode", context=context)
        results = await recall_fn(query="dark mode", context=context)

        assert len(results) >= 1
        assert any("dark mode" in r["content"] for r in results)

    async def test_recall_empty(self, tools: dict, context: ToolContext) -> None:
        recall_fn = tools["memory_recall"]["func"]
        results = await recall_fn(query="nonexistent", context=context)
        assert results == []

    async def test_recall_no_context_returns_error(self, tools: dict) -> None:
        recall_fn = tools["memory_recall"]["func"]
        result = await recall_fn(query="test")
        assert isinstance(result, list)
        assert result[0].get("error")


class TestMemoryForgetTool:
    async def test_forget_saved_memory(self, tools: dict, context: ToolContext) -> None:
        save_fn = tools["memory_save"]["func"]
        forget_fn = tools["memory_forget"]["func"]

        save_result = await save_fn(content="temporary fact", context=context)
        memory_id = save_result["id"]

        result = await forget_fn(memory_id=memory_id, context=context)
        assert result["deleted"] is True

    async def test_forget_nonexistent(self, tools: dict, context: ToolContext) -> None:
        forget_fn = tools["memory_forget"]["func"]
        result = await forget_fn(memory_id="nope", context=context)
        assert result["deleted"] is False

    async def test_forget_no_context_returns_error(self, tools: dict) -> None:
        forget_fn = tools["memory_forget"]["func"]
        result = await forget_fn(memory_id="x")
        assert "error" in result
