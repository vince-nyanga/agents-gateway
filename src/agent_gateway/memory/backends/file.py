"""File-based memory backend using MEMORY.md per agent.

Stores memories as structured markdown sections grouped by type.
Zero infrastructure — human-readable, git-committable, inspectable.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemorySource,
    MemoryType,
)

logger = logging.getLogger(__name__)

_SECTION_HEADING = re.compile(r"^## (Semantic|Episodic|Procedural)\s*$")
_MEMORY_LINE = re.compile(
    r"^- (?:\[([^\]]+)\] )?(.+)$"  # optional [id] prefix, then content
)

_SAFE_AGENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

_TYPE_TO_HEADING: dict[MemoryType, str] = {
    MemoryType.SEMANTIC: "Semantic",
    MemoryType.EPISODIC: "Episodic",
    MemoryType.PROCEDURAL: "Procedural",
}
_HEADING_TO_TYPE: dict[str, MemoryType] = {v: k for k, v in _TYPE_TO_HEADING.items()}


class FileMemoryRepository:
    """Repository that reads/writes structured markdown files.

    .. note::
        All file I/O is synchronous (stdlib ``pathlib``/``open``).  This is
        intentional for the default zero-dependency backend: memory operations
        are infrequent and the files are small (< 100 KB).  For
        high-throughput scenarios, swap in an async backend (e.g. pgvector)
        via ``gateway.set_memory_backend()``.
    """

    def __init__(self, workspace_root: Path, max_lines: int = 200) -> None:
        self._root = workspace_root
        self._max_lines = max_lines
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, agent_id: str) -> asyncio.Lock:
        if agent_id not in self._locks:
            self._locks[agent_id] = asyncio.Lock()
        return self._locks[agent_id]

    def _memory_path(self, agent_id: str) -> Path:
        if not _SAFE_AGENT_ID.match(agent_id):
            raise ValueError(f"Invalid agent_id: {agent_id!r}")
        path = self._root / "agents" / agent_id / "MEMORY.md"
        # Defense-in-depth: verify resolved path stays within workspace
        if not path.resolve().is_relative_to(self._root.resolve()):
            raise ValueError(f"Path traversal detected for agent_id: {agent_id!r}")
        return path

    def _parse_file(self, agent_id: str) -> list[MemoryRecord]:
        """Parse MEMORY.md into MemoryRecord objects."""
        path = self._memory_path(agent_id)
        if not path.exists():
            return []

        content = path.read_text(encoding="utf-8")
        records: list[MemoryRecord] = []
        current_type = MemoryType.SEMANTIC
        now = datetime.now(UTC)

        for line in content.splitlines():
            heading_match = _SECTION_HEADING.match(line)
            if heading_match:
                current_type = _HEADING_TO_TYPE[heading_match.group(1)]
                continue

            mem_match = _MEMORY_LINE.match(line)
            if mem_match:
                memory_id = mem_match.group(1) or uuid.uuid4().hex[:8]
                memory_content = mem_match.group(2)
                records.append(
                    MemoryRecord(
                        id=memory_id,
                        agent_id=agent_id,
                        content=memory_content,
                        memory_type=current_type,
                        source=MemorySource.MANUAL,
                        created_at=now,
                        updated_at=now,
                    )
                )

        return records

    def _write_records(self, agent_id: str, records: list[MemoryRecord]) -> None:
        """Write records to MEMORY.md as structured markdown."""
        path = self._memory_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        grouped: dict[MemoryType, list[MemoryRecord]] = {
            MemoryType.SEMANTIC: [],
            MemoryType.EPISODIC: [],
            MemoryType.PROCEDURAL: [],
        }
        for r in records:
            grouped[r.memory_type].append(r)

        lines: list[str] = []
        for mem_type, heading in _TYPE_TO_HEADING.items():
            type_records = grouped[mem_type]
            if not type_records:
                continue
            lines.append(f"## {heading}")
            for r in type_records:
                lines.append(f"- [{r.id}] {r.content}")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    async def save(self, record: MemoryRecord) -> None:
        async with self._lock_for(record.agent_id):
            records = self._parse_file(record.agent_id)

            # Upsert: replace existing record with same id
            found = False
            for i, r in enumerate(records):
                if r.id == record.id:
                    records[i] = record
                    found = True
                    break

            if not found:
                records.append(record)

            self._write_records(record.agent_id, records)

    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None:
        records = self._parse_file(agent_id)
        for r in records:
            if r.id == memory_id:
                return r
        return None

    async def list_memories(
        self,
        agent_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        records = self._parse_file(agent_id)
        if memory_type is not None:
            records = [r for r in records if r.memory_type == memory_type]
        # Most recent first (by position in file, newest appended last)
        records.reverse()
        return records[offset : offset + limit]

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        """Simple keyword search — case-insensitive matching."""
        records = self._parse_file(agent_id)
        if memory_type is not None:
            records = [r for r in records if r.memory_type == memory_type]

        query_lower = query.lower()
        query_words = query_lower.split()

        results: list[MemorySearchResult] = []
        for r in records:
            content_lower = r.content.lower()
            # Score: fraction of query words found in content
            matches = sum(1 for w in query_words if w in content_lower)
            if matches > 0:
                score = matches / len(query_words) if query_words else 0.0
                results.append(MemorySearchResult(record=r, score=score))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    async def delete(self, agent_id: str, memory_id: str) -> bool:
        async with self._lock_for(agent_id):
            records = self._parse_file(agent_id)
            original_count = len(records)
            records = [r for r in records if r.id != memory_id]
            if len(records) == original_count:
                return False
            self._write_records(agent_id, records)
            return True

    async def delete_all(self, agent_id: str) -> int:
        async with self._lock_for(agent_id):
            records = self._parse_file(agent_id)
            count = len(records)
            if count > 0:
                path = self._memory_path(agent_id)
                path.write_text("", encoding="utf-8")
            return count

    async def count(self, agent_id: str) -> int:
        return len(self._parse_file(agent_id))


class FileMemoryBackend:
    """File-based memory backend using MEMORY.md per agent.

    Zero-config default. Stores memories as structured markdown sections
    grouped by type. Supports keyword search and per-agent asyncio locks.
    """

    def __init__(self, workspace_root: str | Path, max_lines: int = 200) -> None:
        self._root = Path(workspace_root)
        self._max_lines = max_lines
        self._repo = FileMemoryRepository(self._root, max_lines)

    async def initialize(self) -> None:
        pass

    async def dispose(self) -> None:
        pass

    @property
    def memory_repo(self) -> FileMemoryRepository:
        return self._repo
