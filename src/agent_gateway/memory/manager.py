"""MemoryManager — orchestrates memory with LLM-powered extraction."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemorySource,
    MemoryType,
)
from agent_gateway.memory.protocols import MemoryBackend, MemoryRepository

if TYPE_CHECKING:
    from agent_gateway.config import MemoryConfig
    from agent_gateway.engine.llm import LLMClient

logger = logging.getLogger(__name__)

_DEFAULT_EXTRACTION_PROMPT = """\
You are a memory extraction system. Given the following conversation between \
a user and an AI agent, extract discrete, important facts worth remembering \
for future conversations.

Rules:
- Extract facts, preferences, decisions, and outcomes
- Each memory should be a single, self-contained statement
- Classify each as: episodic (what happened), semantic (facts/knowledge), \
or procedural (how to do something)
- Rate importance from 0.0 to 1.0 (only extract items >= 0.3)
- Do NOT extract trivial pleasantries or obvious context
- Synthesize — don't quote verbatim. "User prefers dark mode" not \
"The user said 'I like dark mode'"
- If a fact contradicts an existing memory, note the update

{existing_memories_section}

Respond with ONLY a JSON array (no markdown fences):
[{{"content": "...", "type": "semantic|episodic|procedural", "importance": 0.7}}]

If there is nothing worth remembering, respond with an empty array: []"""


class MemoryManager:
    """Orchestrates memory operations with LLM-powered extraction and compaction."""

    def __init__(
        self,
        backend: MemoryBackend,
        llm_client: LLMClient,
        config: MemoryConfig,
    ) -> None:
        self._backend = backend
        self._llm = llm_client
        self._config = config

    async def dispose(self) -> None:
        """Dispose the underlying memory backend."""
        await self._backend.dispose()

    @property
    def repo(self) -> MemoryRepository:
        return self._backend.memory_repo

    # ── Core CRUD (delegates to repo) ────────────────────────────────

    async def save(self, record: MemoryRecord) -> None:
        """Save a memory record."""
        await self._backend.memory_repo.save(record)

    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None:
        return await self._backend.memory_repo.get(agent_id, memory_id)

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        return await self._backend.memory_repo.search(
            agent_id, query, memory_type=memory_type, limit=limit
        )

    async def delete(self, agent_id: str, memory_id: str) -> bool:
        return await self._backend.memory_repo.delete(agent_id, memory_id)

    # ── LLM-Powered Operations ───────────────────────────────────────

    async def extract_memories(
        self,
        agent_id: str,
        messages: list[dict[str, Any]],
    ) -> list[MemoryRecord]:
        """Extract memorable facts from a conversation using the LLM.

        Deduplicates against existing memories before saving.
        """
        # Get existing memories for dedup context
        existing = await self._backend.memory_repo.list_memories(agent_id, limit=50)
        existing_section = ""
        if existing:
            existing_lines = [f"- {r.content}" for r in existing]
            existing_section = "Existing memories (do not duplicate these):\n" + "\n".join(
                existing_lines
            )

        system_prompt = _DEFAULT_EXTRACTION_PROMPT.format(
            existing_memories_section=existing_section
        )

        extraction_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _format_conversation_for_extraction(messages),
            },
        ]

        try:
            response = await self._llm.completion(
                messages=extraction_messages,
                model=self._config.extraction_model,
                temperature=0.1,
            )
        except Exception:
            logger.warning(
                "Memory extraction failed for agent '%s'",
                agent_id,
                exc_info=True,
            )
            return []

        records = _parse_extraction_response(response.text or "[]", agent_id)

        # Save extracted records
        for record in records:
            await self._backend.memory_repo.save(record)

        if records:
            logger.info(
                "Extracted %d memories for agent '%s'",
                len(records),
                agent_id,
            )

        return records

    async def get_context_block(
        self,
        agent_id: str,
        query: str | None = None,
        max_chars: int | None = None,
    ) -> str:
        """Build the memory block for prompt injection.

        If query is provided, uses relevance-scored search.
        Otherwise, returns most recent memories up to max_chars.
        """
        max_chars = max_chars or self._config.max_injected_chars

        if query:
            results = await self._backend.memory_repo.search(agent_id, query, limit=20)
            records = [r.record for r in results]
        else:
            records = await self._backend.memory_repo.list_memories(agent_id, limit=50)

        if not records:
            return ""

        lines: list[str] = []
        total_chars = 0
        for r in records:
            line = f"- [{r.memory_type.value}] {r.content}"
            if total_chars + len(line) > max_chars:
                break
            lines.append(line)
            total_chars += len(line)

        return "\n".join(lines)


def _format_conversation_for_extraction(messages: list[dict[str, Any]]) -> str:
    """Format conversation messages for the extraction prompt."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _parse_extraction_response(
    text: str,
    agent_id: str,
    source: MemorySource = MemorySource.EXTRACTED,
) -> list[MemoryRecord]:
    """Parse the LLM's JSON array response into MemoryRecords."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last lines (fences)
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse memory extraction response: %s", text[:200])
        return []

    if not isinstance(items, list):
        logger.warning("Memory extraction response is not a list")
        return []

    now = datetime.now(UTC)
    records: list[MemoryRecord] = []
    for item in items:
        if not isinstance(item, dict) or "content" not in item:
            continue

        raw_type = item.get("type", "semantic")
        try:
            memory_type = MemoryType(raw_type)
        except ValueError:
            memory_type = MemoryType.SEMANTIC

        importance = float(item.get("importance", 0.5))
        importance = max(0.0, min(1.0, importance))

        records.append(
            MemoryRecord(
                id=uuid.uuid4().hex[:12],
                agent_id=agent_id,
                content=item["content"],
                memory_type=memory_type,
                source=source,
                importance=importance,
                created_at=now,
                updated_at=now,
            )
        )

    return records
