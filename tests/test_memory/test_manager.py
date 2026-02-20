"""Tests for MemoryManager — LLM-powered extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_gateway.config import MemoryConfig
from agent_gateway.memory.backends.file import FileMemoryBackend
from agent_gateway.memory.domain import MemoryRecord, MemorySource, MemoryType
from agent_gateway.memory.manager import MemoryManager, _parse_extraction_response


@dataclass
class FakeLLMResponse:
    text: str


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "agents" / "test-agent").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def memory_config() -> MemoryConfig:
    return MemoryConfig(enabled=True)


@pytest.fixture
def llm_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
async def manager(
    workspace: Path, llm_client: AsyncMock, memory_config: MemoryConfig
) -> MemoryManager:
    backend = FileMemoryBackend(workspace)
    await backend.initialize()
    return MemoryManager(backend=backend, llm_client=llm_client, config=memory_config)


class TestMemoryManagerCRUD:
    async def test_save_and_get(self, manager: MemoryManager) -> None:
        record = MemoryRecord(id="a", agent_id="test-agent", content="fact")
        await manager.save(record)
        fetched = await manager.get("test-agent", "a")
        assert fetched is not None
        assert fetched.content == "fact"

    async def test_search(self, manager: MemoryManager) -> None:
        await manager.save(
            MemoryRecord(id="a", agent_id="test-agent", content="user prefers dark mode")
        )
        results = await manager.search("test-agent", "dark mode")
        assert len(results) >= 1

    async def test_delete(self, manager: MemoryManager) -> None:
        await manager.save(MemoryRecord(id="a", agent_id="test-agent", content="fact"))
        assert await manager.delete("test-agent", "a") is True
        assert await manager.get("test-agent", "a") is None


class TestMemoryExtraction:
    async def test_extract_memories(self, manager: MemoryManager, llm_client: AsyncMock) -> None:
        llm_client.completion.return_value = FakeLLMResponse(
            text=json.dumps(
                [
                    {"content": "user prefers dark mode", "type": "semantic", "importance": 0.8},
                    {
                        "content": "deployed to prod on friday",
                        "type": "episodic",
                        "importance": 0.6,
                    },
                ]
            )
        )

        messages = [
            {"role": "user", "content": "I prefer dark mode"},
            {"role": "assistant", "content": "Noted, dark mode it is!"},
        ]

        records = await manager.extract_memories("test-agent", messages)
        assert len(records) == 2
        assert records[0].content == "user prefers dark mode"
        assert records[0].source == MemorySource.EXTRACTED

        # Verify they're persisted
        fetched = await manager.search("test-agent", "dark mode")
        assert len(fetched) >= 1

    async def test_extract_handles_llm_failure(
        self, manager: MemoryManager, llm_client: AsyncMock
    ) -> None:
        llm_client.completion.side_effect = RuntimeError("LLM unavailable")
        records = await manager.extract_memories("test-agent", [{"role": "user", "content": "hi"}])
        assert records == []

    async def test_extract_handles_invalid_json(
        self, manager: MemoryManager, llm_client: AsyncMock
    ) -> None:
        llm_client.completion.return_value = FakeLLMResponse(text="not json at all")
        records = await manager.extract_memories("test-agent", [{"role": "user", "content": "hi"}])
        assert records == []


class TestGetContextBlock:
    async def test_empty_when_no_memories(self, manager: MemoryManager) -> None:
        block = await manager.get_context_block("test-agent")
        assert block == ""

    async def test_returns_formatted_block(self, manager: MemoryManager) -> None:
        await manager.save(
            MemoryRecord(
                id="a",
                agent_id="test-agent",
                content="user prefers dark mode",
                memory_type=MemoryType.SEMANTIC,
            )
        )
        block = await manager.get_context_block("test-agent")
        assert "semantic" in block.lower()
        assert "user prefers dark mode" in block

    async def test_respects_max_chars(self, manager: MemoryManager) -> None:
        for i in range(20):
            await manager.save(
                MemoryRecord(
                    id=f"m{i}",
                    agent_id="test-agent",
                    content=f"memory content number {i} with some extra text",
                )
            )
        block = await manager.get_context_block("test-agent", max_chars=200)
        assert len(block) <= 200


class TestParseExtractionResponse:
    def test_valid_json(self) -> None:
        text = json.dumps([{"content": "fact", "type": "semantic", "importance": 0.7}])
        records = _parse_extraction_response(text, "agent-1")
        assert len(records) == 1
        assert records[0].content == "fact"
        assert records[0].memory_type == MemoryType.SEMANTIC
        assert records[0].importance == 0.7

    def test_strips_markdown_fences(self) -> None:
        text = '```json\n[{"content": "fact"}]\n```'
        records = _parse_extraction_response(text, "agent-1")
        assert len(records) == 1

    def test_invalid_json_returns_empty(self) -> None:
        records = _parse_extraction_response("not json", "agent-1")
        assert records == []

    def test_not_a_list_returns_empty(self) -> None:
        records = _parse_extraction_response('{"content": "foo"}', "agent-1")
        assert records == []

    def test_missing_content_skipped(self) -> None:
        text = json.dumps([{"type": "semantic"}, {"content": "valid"}])
        records = _parse_extraction_response(text, "agent-1")
        assert len(records) == 1
        assert records[0].content == "valid"

    def test_invalid_type_defaults_to_semantic(self) -> None:
        text = json.dumps([{"content": "fact", "type": "invalid"}])
        records = _parse_extraction_response(text, "agent-1")
        assert records[0].memory_type == MemoryType.SEMANTIC

    def test_importance_clamped(self) -> None:
        text = json.dumps([{"content": "fact", "importance": 5.0}])
        records = _parse_extraction_response(text, "agent-1")
        assert records[0].importance == 1.0

    def test_source_propagated(self) -> None:
        text = json.dumps([{"content": "fact"}])
        records = _parse_extraction_response(text, "agent-1", source=MemorySource.COMPACTED)
        assert records[0].source == MemorySource.COMPACTED
