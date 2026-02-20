"""Agent memory system — persistent, per-agent memory with pluggable backends."""

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemorySource,
    MemoryType,
)
from agent_gateway.memory.protocols import MemoryBackend, MemoryRepository

__all__ = [
    "MemoryBackend",
    "MemoryRecord",
    "MemoryRepository",
    "MemorySearchResult",
    "MemorySource",
    "MemoryType",
]
