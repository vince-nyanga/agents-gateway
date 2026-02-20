"""Memory domain models — plain dataclasses, zero infrastructure imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class MemoryType(StrEnum):
    """Classification of a memory entry."""

    EPISODIC = "episodic"  # Past interactions, what happened
    SEMANTIC = "semantic"  # Facts, knowledge, preferences
    PROCEDURAL = "procedural"  # Patterns, workflows, how-to


class MemorySource(StrEnum):
    """How a memory entry was created."""

    MANUAL = "manual"  # Written via tool or API
    EXTRACTED = "extracted"  # Auto-extracted by LLM from conversation
    COMPACTED = "compacted"  # Synthesized by LLM from older memories


@dataclass
class MemoryRecord:
    """A single memory entry for an agent."""

    id: str
    agent_id: str
    content: str
    memory_type: MemoryType = MemoryType.SEMANTIC
    source: MemorySource = MemorySource.MANUAL
    importance: float = 0.5
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class MemorySearchResult:
    """A memory record with a relevance score."""

    record: MemoryRecord
    score: float
