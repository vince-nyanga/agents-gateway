"""Tests for file-based memory backend (MEMORY.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_gateway.memory.backends.file import FileMemoryBackend, FileMemoryRepository
from agent_gateway.memory.domain import MemoryRecord, MemoryType


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "agents" / "test-agent").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def repo(workspace: Path) -> FileMemoryRepository:
    return FileMemoryRepository(workspace)


@pytest.fixture
def backend(workspace: Path) -> FileMemoryBackend:
    return FileMemoryBackend(workspace)


def _make_record(
    agent_id: str = "test-agent",
    content: str = "test memory",
    memory_id: str = "mem1",
    memory_type: MemoryType = MemoryType.SEMANTIC,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        agent_id=agent_id,
        content=content,
        memory_type=memory_type,
    )


class TestFileMemoryRepository:
    async def test_save_and_get(self, repo: FileMemoryRepository) -> None:
        record = _make_record()
        await repo.save(record)

        fetched = await repo.get("test-agent", "mem1")
        assert fetched is not None
        assert fetched.content == "test memory"
        assert fetched.memory_type == MemoryType.SEMANTIC

    async def test_save_creates_directory(self, tmp_path: Path) -> None:
        repo = FileMemoryRepository(tmp_path)
        record = _make_record(agent_id="new-agent")
        await repo.save(record)
        assert (tmp_path / "agents" / "new-agent" / "MEMORY.md").exists()

    async def test_upsert_existing(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(content="original"))
        await repo.save(_make_record(content="updated"))

        fetched = await repo.get("test-agent", "mem1")
        assert fetched is not None
        assert fetched.content == "updated"
        assert await repo.count("test-agent") == 1

    async def test_list_memories(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(memory_id="a", content="first"))
        await repo.save(_make_record(memory_id="b", content="second"))
        await repo.save(_make_record(memory_id="c", content="third"))

        records = await repo.list_memories("test-agent")
        assert len(records) == 3
        # Most recent first (reversed order)
        assert records[0].id == "c"

    async def test_list_with_type_filter(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(memory_id="a", memory_type=MemoryType.SEMANTIC))
        await repo.save(_make_record(memory_id="b", memory_type=MemoryType.EPISODIC))
        await repo.save(_make_record(memory_id="c", memory_type=MemoryType.SEMANTIC))

        results = await repo.list_memories("test-agent", memory_type=MemoryType.SEMANTIC)
        assert len(results) == 2

    async def test_list_with_limit(self, repo: FileMemoryRepository) -> None:
        for i in range(5):
            await repo.save(_make_record(memory_id=f"m{i}", content=f"memory {i}"))

        results = await repo.list_memories("test-agent", limit=2)
        assert len(results) == 2

    async def test_search_keyword_match(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(memory_id="a", content="user prefers dark mode"))
        await repo.save(_make_record(memory_id="b", content="project uses Python 3.12"))
        await repo.save(_make_record(memory_id="c", content="user likes vim"))

        results = await repo.search("test-agent", "user prefers")
        assert len(results) >= 1
        assert results[0].record.content == "user prefers dark mode"
        assert results[0].score > 0

    async def test_search_no_match(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(content="something unrelated"))
        results = await repo.search("test-agent", "nonexistent query words")
        assert len(results) == 0

    async def test_search_case_insensitive(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(content="User Prefers DARK mode"))
        results = await repo.search("test-agent", "dark")
        assert len(results) == 1

    async def test_delete(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(memory_id="a"))
        await repo.save(_make_record(memory_id="b"))

        deleted = await repo.delete("test-agent", "a")
        assert deleted is True
        assert await repo.count("test-agent") == 1
        assert await repo.get("test-agent", "a") is None

    async def test_delete_nonexistent(self, repo: FileMemoryRepository) -> None:
        assert await repo.delete("test-agent", "nope") is False

    async def test_delete_all(self, repo: FileMemoryRepository) -> None:
        await repo.save(_make_record(memory_id="a"))
        await repo.save(_make_record(memory_id="b"))

        count = await repo.delete_all("test-agent")
        assert count == 2
        assert await repo.count("test-agent") == 0

    async def test_count(self, repo: FileMemoryRepository) -> None:
        assert await repo.count("test-agent") == 0
        await repo.save(_make_record(memory_id="a"))
        assert await repo.count("test-agent") == 1

    async def test_path_traversal_rejected(self, repo: FileMemoryRepository) -> None:
        with pytest.raises(ValueError, match="Invalid agent_id"):
            await repo.get("../../etc", "some-id")

    async def test_path_traversal_dotdot_rejected(self, repo: FileMemoryRepository) -> None:
        with pytest.raises(ValueError, match="Invalid agent_id"):
            await repo.count("../other-agent")

    async def test_agent_isolation(self, repo: FileMemoryRepository, workspace: Path) -> None:
        (workspace / "agents" / "other-agent").mkdir(parents=True)
        await repo.save(_make_record(agent_id="test-agent", memory_id="a"))
        await repo.save(_make_record(agent_id="other-agent", memory_id="b"))

        assert await repo.count("test-agent") == 1
        assert await repo.count("other-agent") == 1
        assert await repo.get("test-agent", "b") is None


class TestFileMemoryMarkdownFormat:
    async def test_markdown_structure(self, repo: FileMemoryRepository, workspace: Path) -> None:
        await repo.save(
            _make_record(memory_id="s1", content="fact one", memory_type=MemoryType.SEMANTIC)
        )
        await repo.save(
            _make_record(memory_id="e1", content="event one", memory_type=MemoryType.EPISODIC)
        )

        path = workspace / "agents" / "test-agent" / "MEMORY.md"
        content = path.read_text()
        assert "## Semantic" in content
        assert "## Episodic" in content
        assert "- [s1] fact one" in content
        assert "- [e1] event one" in content

    async def test_roundtrip_preserves_content(
        self, repo: FileMemoryRepository, workspace: Path
    ) -> None:
        await repo.save(_make_record(memory_id="x", content="special chars: [brackets] & more"))
        fetched = await repo.get("test-agent", "x")
        assert fetched is not None
        assert fetched.content == "special chars: [brackets] & more"


class TestFileMemoryBackend:
    async def test_lifecycle(self, backend: FileMemoryBackend) -> None:
        await backend.initialize()
        assert backend.memory_repo is not None
        await backend.dispose()
