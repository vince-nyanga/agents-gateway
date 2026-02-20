"""Tests for memory domain model."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemorySource,
    MemoryType,
)


class TestMemoryType:
    def test_values(self) -> None:
        assert MemoryType.EPISODIC == "episodic"
        assert MemoryType.SEMANTIC == "semantic"
        assert MemoryType.PROCEDURAL == "procedural"

    def test_from_string(self) -> None:
        assert MemoryType("semantic") == MemoryType.SEMANTIC


class TestMemorySource:
    def test_values(self) -> None:
        assert MemorySource.MANUAL == "manual"
        assert MemorySource.EXTRACTED == "extracted"
        assert MemorySource.COMPACTED == "compacted"


class TestMemoryRecord:
    def test_defaults(self) -> None:
        record = MemoryRecord(
            id="abc",
            agent_id="test-agent",
            content="user prefers dark mode",
        )
        assert record.memory_type == MemoryType.SEMANTIC
        assert record.source == MemorySource.MANUAL
        assert record.importance == 0.5
        assert isinstance(record.created_at, datetime)

    def test_explicit_values(self) -> None:
        now = datetime.now(UTC)
        record = MemoryRecord(
            id="xyz",
            agent_id="agent-1",
            content="deploy to prod on fridays",
            memory_type=MemoryType.PROCEDURAL,
            source=MemorySource.EXTRACTED,
            importance=0.9,
            created_at=now,
            updated_at=now,
        )
        assert record.memory_type == MemoryType.PROCEDURAL
        assert record.source == MemorySource.EXTRACTED
        assert record.importance == 0.9


class TestMemorySearchResult:
    def test_fields(self) -> None:
        record = MemoryRecord(id="a", agent_id="x", content="test")
        result = MemorySearchResult(record=record, score=0.85)
        assert result.score == 0.85
        assert result.record.content == "test"
