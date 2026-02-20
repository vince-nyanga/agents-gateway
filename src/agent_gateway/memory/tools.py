"""Built-in memory tools — agents use these to manage their own memory."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_gateway.memory.domain import MemoryRecord, MemorySource, MemoryType

if TYPE_CHECKING:
    from agent_gateway.engine.models import ToolContext
    from agent_gateway.memory.manager import MemoryManager


def make_memory_tools(
    memory_manager: MemoryManager,
) -> list[dict[str, Any]]:
    """Create memory tool functions bound to a MemoryManager.

    Returns a list of (name, func, description, parameters) tuples
    suitable for registration as code tools.
    """

    async def memory_recall(
        query: str,
        memory_type: str | None = None,
        limit: int = 5,
        context: ToolContext | None = None,
    ) -> list[dict[str, Any]]:
        """Search the agent's memory for relevant past knowledge.

        Args:
            query: Natural language query to search memories.
            memory_type: Filter by type (episodic, semantic, procedural). Optional.
            limit: Maximum results to return. Default 5.
        """
        if context is None:
            return [{"error": "No tool context available"}]

        mt = None
        if memory_type:
            with contextlib.suppress(ValueError):
                mt = MemoryType(memory_type)

        results = await memory_manager.search(context.agent_id, query, memory_type=mt, limit=limit)
        return [
            {
                "id": r.record.id,
                "content": r.record.content,
                "type": r.record.memory_type.value,
                "importance": r.record.importance,
                "score": r.score,
            }
            for r in results
        ]

    async def memory_save(
        content: str,
        memory_type: str = "semantic",
        importance: float = 0.5,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Save a new memory for future reference.

        Args:
            content: The fact, knowledge, or pattern to remember.
            memory_type: One of: episodic, semantic, procedural.
            importance: How important this memory is (0.0-1.0).
        """
        if context is None:
            return {"error": "No tool context available"}

        if len(content) > 2000:
            return {"error": "Content exceeds maximum length of 2000 characters"}

        try:
            mt = MemoryType(memory_type)
        except ValueError:
            mt = MemoryType.SEMANTIC

        now = datetime.now(UTC)
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            agent_id=context.agent_id,
            content=content,
            memory_type=mt,
            source=MemorySource.MANUAL,
            importance=max(0.0, min(1.0, importance)),
            created_at=now,
            updated_at=now,
        )

        await memory_manager.save(record)
        return {"id": record.id, "status": "saved"}

    async def memory_forget(
        memory_id: str,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Delete a specific memory by ID.

        Args:
            memory_id: The ID of the memory to forget.
        """
        if context is None:
            return {"error": "No tool context available"}

        deleted = await memory_manager.delete(context.agent_id, memory_id)
        return {"deleted": deleted}

    return [
        {
            "name": "memory_recall",
            "func": memory_recall,
            "description": (
                "Search the agent's memory for relevant past knowledge, "
                "facts, preferences, or patterns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query to search memories.",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "semantic", "procedural"],
                        "description": "Filter by memory type. Optional.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return. Default 5.",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "memory_save",
            "func": memory_save,
            "description": (
                "Save a new memory (fact, preference, pattern) "
                "for future reference across conversations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The fact, knowledge, or pattern to remember.",
                        "maxLength": 2000,
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "semantic", "procedural"],
                        "description": "Type of memory. Default: semantic.",
                    },
                    "importance": {
                        "type": "number",
                        "description": "How important this memory is (0.0-1.0). Default: 0.5.",
                    },
                },
                "required": ["content"],
            },
        },
        {
            "name": "memory_forget",
            "func": memory_forget,
            "description": "Delete a specific memory by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "The ID of the memory to forget.",
                    },
                },
                "required": ["memory_id"],
            },
        },
    ]
