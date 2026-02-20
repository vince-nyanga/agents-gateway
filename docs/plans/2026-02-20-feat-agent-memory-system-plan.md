---
title: "feat: Add Per-Agent Memory System"
type: feat
status: active
date: 2026-02-20
---

# feat: Add Per-Agent Memory System

## Overview

Add an extensible, per-agent memory system to agent-gateway. Agents gain persistent memory across conversations -- synthesized and compacted by an LLM, not raw data dumps. The system supports two complementary layers: **file-based memory** (MEMORY.md loaded into prompts, like Claude Code) and **persisted memory** (structured storage with search via a pluggable backend protocol). An LLM model is responsible for memory extraction, synthesis, and compaction.

## Problem Statement / Motivation

Agents today are stateless across conversations. Each invocation starts fresh with no knowledge of prior interactions, learned user preferences, or accumulated facts. This limits agents to transactional interactions and prevents them from building long-term relationships with users or improving over time.

Key use cases:
- **User preferences**: "I prefer metric units" remembered across sessions
- **Learned facts**: "The project uses FastAPI with SQLAlchemy" persisted from a discovery conversation
- **Task patterns**: "Last time we deployed, the health check needed 30s warmup" recalled when relevant
- **Conversation synthesis**: Key decisions and outcomes from past interactions, not raw transcripts

## Proposed Solution

A two-layer memory architecture following the project's existing Protocol-based extensibility pattern:

```
┌─────────────────────────────────────────────┐
│              Memory Tools                    │
│  memory-recall | memory-save | memory-forget │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│           MemoryManager (Service)            │
│  - retrieve (relevance-scored)               │
│  - store (with type + metadata)              │
│  - extract (LLM-powered, from conversation)  │
│  - compact (LLM-powered, synthesis)          │
│  - get_context_block (for prompt injection)   │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│      MemoryBackend (Protocol)                │
│  - initialize() / dispose()                  │
│  - memory_repo: MemoryRepository             │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┼───────┐
       │       │       │
  ┌────▼──┐ ┌──▼──┐ ┌──▼──────────────┐
  │  Null │ │File │ │ Your own impl   │
  │(no-op)│ │(.md)│ │ (SQLite+vec,    │
  └───────┘ └─────┘ │  Postgres+pgvec,│
                     │  Pinecone, etc.)│
                     └─────────────────┘
```

We ship the **protocol** and a **file backend** (MEMORY.md). Consumers who need vector search, SQL storage, or any other strategy implement the `MemoryBackend` protocol themselves. This avoids the framework having opinions about embedding dimensions, vector DBs, or search strategies.

### Design Principles

1. **Protocol-first**: `MemoryBackend` + `MemoryRepository` as `@runtime_checkable Protocol` classes, matching `PersistenceBackend`/`ContextRetriever` patterns
2. **LLM as the brain**: Extraction, synthesis, and compaction are all LLM-powered -- memories are processed knowledge, not raw logs
3. **Per-agent isolation**: Memory is scoped by `agent_id`. No cross-agent access
4. **File backend as default**: MEMORY.md is the zero-config, zero-dependency default
5. **Consumers own their backends**: Different models produce different embedding dimensions. Different teams use different vector DBs. We expose the protocol; they decide
6. **Null by default**: When no backend is configured, `NullMemoryBackend` silently no-ops (like every other subsystem)

## Technical Approach

### Phase 1: Domain Model + Protocol Layer

**New directory**: `src/agent_gateway/memory/`

#### Memory Record (Domain)

```python
# src/agent_gateway/memory/domain.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

class MemoryType(str, Enum):
    EPISODIC = "episodic"      # Past interactions, what happened
    SEMANTIC = "semantic"       # Facts, knowledge, preferences
    PROCEDURAL = "procedural"  # Patterns, workflows, how-to

class MemorySource(str, Enum):
    MANUAL = "manual"           # Written via tool or API
    EXTRACTED = "extracted"     # Auto-extracted by LLM from conversation
    COMPACTED = "compacted"     # Synthesized by LLM from older memories
    SEED = "seed"               # Loaded from MEMORY.md

@dataclass
class MemoryRecord:
    id: str
    agent_id: str
    content: str
    memory_type: MemoryType = MemoryType.SEMANTIC
    source: MemorySource = MemorySource.MANUAL
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5     # 0.0-1.0, influences retrieval ranking
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    access_count: int = 0

@dataclass
class MemorySearchResult:
    record: MemoryRecord
    score: float                # Relevance score from search
```

#### Protocol Interfaces

```python
# src/agent_gateway/memory/protocols.py
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class MemoryRepository(Protocol):
    """Storage and retrieval contract for agent memories."""

    async def save(self, record: MemoryRecord) -> None:
        """Upsert a memory record (insert or update by id)."""
        ...

    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory by ID."""
        ...

    async def list(
        self,
        agent_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List memories with optional type filter, ordered by updated_at desc."""
        ...

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        """Search memories by relevance. Backend decides search strategy."""
        ...

    async def delete(self, agent_id: str, memory_id: str) -> bool:
        """Delete a memory. Returns True if it existed."""
        ...

    async def delete_all(self, agent_id: str) -> int:
        """Delete all memories for an agent. Returns count deleted."""
        ...

    async def count(self, agent_id: str) -> int:
        """Count memories for an agent."""
        ...


@runtime_checkable
class MemoryBackend(Protocol):
    """Top-level memory backend with lifecycle management."""

    async def initialize(self) -> None:
        """Create tables/indexes. Must be idempotent."""
        ...

    async def dispose(self) -> None:
        """Close connections and release resources."""
        ...

    @property
    def memory_repo(self) -> MemoryRepository:
        ...
```

#### Null Implementation

```python
# src/agent_gateway/memory/null.py
class NullMemoryRepository:
    """No-op repository when memory is disabled."""
    async def save(self, record): pass
    async def get(self, agent_id, memory_id): return None
    async def list(self, agent_id, **kw): return []
    async def search(self, agent_id, query, **kw): return []
    async def delete(self, agent_id, memory_id): return False
    async def delete_all(self, agent_id): return 0
    async def count(self, agent_id): return 0

class NullMemoryBackend:
    async def initialize(self): pass
    async def dispose(self): pass
    @property
    def memory_repo(self) -> NullMemoryRepository:
        return NullMemoryRepository()
```

#### Exceptions

Add to `src/agent_gateway/exceptions.py`:

```python
class MemoryError(AgentGatewayError):
    """Base for memory-related errors."""

class MemoryBackendError(MemoryError):
    """Memory backend failure (connection, query, etc.)."""

class MemoryCompactionError(MemoryError):
    """LLM compaction failed."""
```

### Phase 2: File Memory Backend (MEMORY.md)

The file backend is the zero-config `MemoryBackend` implementation. It stores memories as structured markdown in `workspace/agents/<name>/MEMORY.md`. No database required -- human-readable, git-committable, inspectable.

```python
# src/agent_gateway/memory/backends/file.py
class FileMemoryBackend:
    """File-based memory backend using MEMORY.md per agent.

    Stores memories as structured markdown sections grouped by type.
    Supports read, write, delete, and basic keyword search.
    Enforces a max line cap to prevent context pollution.
    """

    def __init__(self, workspace_root: Path, max_lines: int = 200):
        self._root = workspace_root
        self._max_lines = max_lines

    def _memory_path(self, agent_id: str) -> Path:
        return self._root / "agents" / agent_id / "MEMORY.md"
```

#### File Format

MEMORY.md is a structured markdown file written and maintained by the system:

```markdown
## Semantic
- User prefers metric units
- The project uses FastAPI with SQLAlchemy

## Episodic
- 2026-02-20: Deployed v2.1, health check needed 30s warmup
- 2026-02-19: User reported timeout on large file uploads

## Procedural
- When deploying, always check the health endpoint after 30s
- For file uploads > 10MB, use chunked transfer
```

#### Size Cap

MEMORY.md is capped at `max_memory_md_lines` (default: 200). When loading for prompt injection, lines beyond the cap are truncated and a warning is logged. When a write would exceed the cap, it triggers compaction first (via `MemoryManager`) to synthesize and reduce the file before appending.

#### Search

The file backend implements `search()` using simple keyword matching against memory content. This is intentionally basic -- developers who need full-text or semantic search should use the SQLite or Postgres backends.

#### Concurrency

File writes use a per-agent asyncio lock to prevent concurrent write corruption. This is sufficient for single-process deployments. Multi-process deployments should use a SQL backend.

#### Prompt Assembly

Add a new layer in `assemble_system_prompt()` at `src/agent_gateway/workspace/prompt.py`:

```
Current order:
1. Date/time
2. Root AGENTS.md
3. Root BEHAVIOR.md
4. Agent AGENT.md
5. Agent BEHAVIOR.md
6. Static context files ("## Reference Material")
7. Dynamic retriever results ("## Retrieved Context")
8. Skill instructions ("## Available Skills")

New order (memory inserted between behavior and context):
1. Date/time
2. Root AGENTS.md
3. Root BEHAVIOR.md
4. Agent AGENT.md
5. Agent BEHAVIOR.md
6. **Agent memories ("## Agent Memory")**              ← NEW (from backend)
7. Static context files ("## Reference Material")
8. Dynamic retriever results ("## Retrieved Context")
9. Skill instructions ("## Available Skills")
```

Memory goes before context because it represents the agent's own knowledge (higher priority), while context is external reference material. The `MemoryManager.get_context_block()` method reads from whatever backend is configured (file, SQLite, or Postgres) and formats it for injection, capped at `max_injected_chars`.

#### AGENT.md Frontmatter

Add a `memory:` block to agent frontmatter:

```yaml
# workspace/agents/my-agent/AGENT.md
---
name: My Agent
memory:
  enabled: true              # Enable memory tools + backend
  auto_extract: false        # Auto-extract memories from conversations
  max_injected_chars: 4000   # Cap for memory content injected into prompt
  max_memory_md_lines: 200   # Max lines for file backend (triggers compaction)
---
```

When `memory.enabled` is false (default), no memory tools are registered and no memory is injected into prompts.

### Phase 3: MemoryManager (LLM-Powered Service)

The `MemoryManager` is the central service that orchestrates memory operations. It wraps the backend repository and adds LLM intelligence on top.

```python
# src/agent_gateway/memory/manager.py
class MemoryManager:
    """Orchestrates memory operations with LLM-powered extraction and compaction."""

    def __init__(
        self,
        backend: MemoryBackend,
        llm_client: LLMClient,       # For extraction + compaction
        config: MemoryConfig,
    ):
        self._backend = backend
        self._llm = llm_client
        self._config = config

    @property
    def repo(self) -> MemoryRepository:
        return self._backend.memory_repo

    # --- Core CRUD (delegates to repo) ---

    async def save(self, record: MemoryRecord) -> None: ...
    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None: ...
    async def search(self, agent_id: str, query: str, **kw) -> list[MemorySearchResult]: ...
    async def delete(self, agent_id: str, memory_id: str) -> bool: ...

    # --- LLM-Powered Operations ---

    async def extract_memories(
        self,
        agent_id: str,
        messages: list[dict],
        agent_prompt: str,
    ) -> list[MemoryRecord]:
        """Extract memorable facts from a conversation using the LLM.

        The LLM receives the conversation + the agent's purpose and returns
        structured memory entries (facts, preferences, outcomes).
        Deduplicates against existing memories before saving.
        """
        ...

    async def compact(self, agent_id: str) -> CompactionResult:
        """Synthesize and compact memories for an agent using the LLM.

        1. Load all memories for the agent
        2. Group by type
        3. Send to LLM with instructions to synthesize, merge duplicates,
           and discard low-value entries
        4. Replace old memories with compacted versions (transactional)
        5. Mark compacted memories with source=COMPACTED

        Returns a CompactionResult with before/after counts.
        """
        ...

    async def get_context_block(
        self,
        agent_id: str,
        query: str | None = None,
        max_chars: int = 4000,
    ) -> str:
        """Build the memory block for prompt injection.

        If query is provided, uses relevance-scored search.
        Otherwise, returns most recent memories up to max_chars.
        Formats as a markdown section for prompt injection.
        """
        ...
```

#### Extraction Prompt (Default)

The LLM model handles extraction. The prompt is configurable per agent via `memory.extraction_prompt` in AGENT.md frontmatter, with a sensible default:

```
You are a memory extraction system. Given the following conversation between
a user and an AI agent, extract discrete, important facts worth remembering
for future conversations.

Rules:
- Extract facts, preferences, decisions, and outcomes
- Each memory should be a single, self-contained statement
- Classify each as: episodic (what happened), semantic (facts/knowledge),
  or procedural (how to do something)
- Rate importance from 0.0 to 1.0 (only extract items >= 0.3)
- Do NOT extract trivial pleasantries or obvious context
- Synthesize -- don't quote verbatim. "User prefers dark mode" not
  "The user said 'I like dark mode'"
- If a fact contradicts an existing memory, note the update

Respond as JSON array:
[{"content": "...", "type": "semantic|episodic|procedural", "importance": 0.7}]
```

#### Compaction Prompt (Default)

```
You are a memory compaction system. Review the following memories for agent
"{agent_id}" and produce a synthesized, deduplicated set.

Rules:
- Merge duplicate or overlapping facts into single entries
- Discard memories that are outdated or superseded by newer ones
- Preserve high-importance memories verbatim
- Combine related low-importance memories into summaries
- Maintain the type classification (episodic/semantic/procedural)
- Target: reduce to at most {target_count} memories
- Preserve the most recent and most accessed memories

Current memories:
{memories_json}

Respond as JSON array with the compacted memories.
```

#### Compaction Trigger

Compaction runs when:
1. **Threshold exceeded**: After each memory save, check `count(agent_id)` against `memory.compact_threshold` (default: 100). If exceeded, schedule compaction as a background task
2. **Programmatic**: Call `memory_manager.compact(agent_id)` directly
3. **Optional cron**: If the agent has a compaction schedule in frontmatter

Compaction is **transactional**: old memories are deleted and compacted memories are saved in a single operation. If the LLM call fails, original memories are preserved.

### Phase 4: Memory Tools (Agent Self-Management)

Memory tools follow the Letta pattern -- the agent decides what to remember and what to recall. These are registered as built-in code tools (not workspace tools) when `memory.enabled: true`.

#### Tool Definitions

```python
# src/agent_gateway/memory/tools.py

async def memory_recall(
    query: str,
    memory_type: str | None = None,
    limit: int = 5,
    context: ToolContext = ...,
) -> list[dict]:
    """Search the agent's memory for relevant past knowledge.

    Args:
        query: Natural language query to search memories.
        memory_type: Filter by type (episodic, semantic, procedural). Optional.
        limit: Maximum results to return. Default 5.
    """
    ...

async def memory_save(
    content: str,
    memory_type: str = "semantic",
    importance: float = 0.5,
    context: ToolContext = ...,
) -> dict:
    """Save a new memory for future reference.

    Args:
        content: The fact, knowledge, or pattern to remember.
        memory_type: One of: episodic, semantic, procedural.
        importance: How important this memory is (0.0-1.0).
    """
    ...

async def memory_forget(
    memory_id: str,
    context: ToolContext = ...,
) -> dict:
    """Delete a specific memory by ID.

    Args:
        memory_id: The ID of the memory to forget.
    """
    ...
```

#### Registration

Memory tools are registered as internal code tools during `_startup()`, scoped to agents with `memory.enabled: true`. They are added to the agent's available tools alongside skill-provided tools.

The `ToolContext` carries `agent_id`, ensuring memory operations are always scoped to the calling agent.

### Phase 5: Auto-Extraction

When `memory.auto_extract: true` in an agent's frontmatter, the system automatically extracts memories after each chat conversation.

#### Trigger Point

After `Gateway.chat()` returns a response and the chat session is updated, a **background task** (fire-and-forget) calls `MemoryManager.extract_memories()` with the conversation messages.

```python
# In the chat flow, after getting the LLM response:
if agent_memory_config.auto_extract:
    asyncio.create_task(
        memory_manager.extract_memories(
            agent_id=agent_id,
            messages=session.messages,
            agent_prompt=agent.agent_prompt,
        )
    )
```

This is async/background so it does not add latency to the response. Extracted memories are available from the next turn onward.

#### Deduplication

`extract_memories()` queries existing memories and includes them in the extraction prompt so the LLM can avoid duplicates. The extraction prompt includes a section:

```
Existing memories (do not duplicate these):
{existing_memories}
```

### Phase 6: Gateway Integration

#### Fluent API

Add to `gateway.py`, following the pending registration pattern:

```python
class Gateway(FastAPI):
    def __init__(self, ...):
        ...
        self._pending_memory_backend: MemoryBackend | None = None

    def use_memory(self, backend: MemoryBackend) -> Gateway:
        """Configure a memory backend. Must be called before startup."""
        if self._started:
            raise RuntimeError("Cannot configure memory after gateway has started")
        self._pending_memory_backend = backend
        return self

    # Convenience method for built-in file backend
    def use_file_memory(self, max_lines: int = 200) -> Gateway:
        """File-based memory using MEMORY.md per agent. Zero-config default."""
        from agent_gateway.memory.backends.file import FileMemoryBackend
        return self.use_memory(FileMemoryBackend(self._workspace_path, max_lines))
```

#### Startup Integration

In `_startup()`, after persistence initialization:

```python
# Initialize memory backend
memory_backend = self._pending_memory_backend or NullMemoryBackend()
await memory_backend.initialize()

# Create MemoryManager
self._memory_manager = MemoryManager(
    backend=memory_backend,
    llm_client=llm_client,
    config=self._config.memory,
)

# Register memory tools for enabled agents
for agent in workspace.agents.values():
    if agent.memory_config and agent.memory_config.enabled:
        self._register_memory_tools(agent.id)
```

#### Shutdown

In `_shutdown()`:
```python
await self._memory_manager._backend.dispose()
```

### Phase 7: Configuration

Add to `GatewayConfig` in `src/agent_gateway/config.py`:

```python
@dataclass
class MemoryConfig:
    """Global memory defaults (overridable per-agent in AGENT.md)."""
    enabled: bool = False
    max_injected_chars: int = 4000
    compact_threshold: int = 100       # Compact when memory count exceeds this
    compact_target: int = 50           # Target count after compaction
    extraction_model: str | None = None  # LLM model for extraction/compaction (None = agent's model)
    auto_extract: bool = False
    max_memory_md_lines: int = 200     # Max lines loaded from MEMORY.md (truncated with warning)
```

## Acceptance Criteria

### Functional Requirements

- [ ] `MemoryBackend` + `MemoryRepository` protocols defined with `@runtime_checkable`
- [ ] `NullMemoryBackend` implementation (no-op when memory disabled)
- [ ] `FileMemoryBackend` using MEMORY.md per agent (read/write, keyword search, line cap with compaction)
- [ ] Protocol is sufficient for consumers to implement vector search backends (no framework opinions on embeddings)
- [ ] `MemoryManager` with LLM-powered `extract_memories()` and `compact()`
- [ ] `memory-recall`, `memory-save`, `memory-forget` tools registered for memory-enabled agents
- [ ] Auto-extraction as async background task after chat turns (when enabled)
- [ ] Compaction triggered by threshold or programmatically
- [ ] Gateway fluent API: `use_memory()` (any backend), `use_file_memory()` (built-in convenience)
- [ ] `memory:` block in AGENT.md frontmatter parsed and applied
- [ ] Memory isolation enforced by agent_id scoping at repository level

### Non-Functional Requirements

- [ ] File backend has zero external dependencies
- [ ] Compaction is transactional -- originals preserved on LLM failure
- [ ] Auto-extraction does not add latency to chat responses (runs in background)
- [ ] Memory content redacted from telemetry spans

### Quality Gates

- [ ] Unit tests for domain model, protocols, null backend, manager
- [ ] Integration tests for file backend
- [ ] Test for compaction failure recovery (LLM error preserves originals)
- [ ] Test for memory isolation (agent A cannot access agent B's memories)
- [ ] Example project updated to demonstrate memory feature

## Dependencies & Risks

**Dependencies:**
- Existing `LLMClient` for extraction/compaction calls
- Existing `ToolContext` for scoping memory tools to agents

**Risks:**
- **LLM cost**: Every auto-extraction is an additional LLM call. Mitigated by configurable model (`extraction_model`) and opt-in per agent
- **Context window overflow**: Accumulated memories could exceed prompt budget. Mitigated by `max_injected_chars` cap
- **Compaction data loss**: LLM could lose important information during synthesis. Mitigated by transactional compaction + keeping high-importance memories verbatim

## Future Considerations

These are explicitly **out of scope** for v1 but the protocol is designed to support them:

- **Vector search backends**: Consumers implement `MemoryBackend` with their preferred stack (e.g., Postgres+pgvector, SQLite+sqlite-vec, Pinecone, Qdrant). Different models produce different embedding dimensions -- that's the consumer's concern, not the framework's

```python
# Example: consumer-built vector backend
class PgVectorMemoryBackend:
    def __init__(self, dsn: str, embed_fn, dimensions: int):
        ...

gw.use_memory(PgVectorMemoryBackend(
    dsn="postgresql://...",
    embed_fn=openai_embed,
    dimensions=1536,
))
```

- **REST API**: CRUD + search + compact endpoints under `/agents/{agent_id}/memory` for external inspection and management
- **Cross-agent shared memory**: Shared memory namespaces between agents
- **Memory import/export**: Bulk operations for migration between backends
- **User-scoped memory**: Memory scoped by `(agent_id, user_id)` tuple for multi-user scenarios
- **Memory retention policies**: TTL-based expiry, GDPR purge endpoints
- **Custom extraction prompts**: Per-agent prompt overrides for domain-specific extraction

## References & Research

### Internal References

- Persistence backend pattern: `src/agent_gateway/persistence/backend.py:15`
- Protocol pattern: `src/agent_gateway/persistence/protocols.py:17`
- Null backend pattern: `src/agent_gateway/persistence/null.py`
- Context retriever protocol: `src/agent_gateway/context/protocol.py:9`
- Prompt assembly: `src/agent_gateway/workspace/prompt.py:19`
- Agent loading: `src/agent_gateway/workspace/agent.py:66`
- Tool context: `src/agent_gateway/engine/models.py:139`
- Gateway pending registration: `src/agent_gateway/gateway.py:97-99`
- Hooks system: `src/agent_gateway/hooks.py:14`

### External References

- [Letta (MemGPT) Memory Architecture](https://docs.letta.com/guides/agents/architectures/memgpt/) -- tiered memory model, agent-controlled memory tools
- [LangGraph Memory](https://docs.langchain.com/oss/python/langgraph/persistence) -- checkpointer + store dual model, namespace tuples
- [CrewAI Memory](https://docs.crewai.com/en/concepts/memory) -- composite scoring (semantic + recency + importance)
- [Google ADK Memory](https://google.github.io/adk-docs/sessions/memory/) -- `add_session_to_memory`, scoped state prefixes
- [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/) -- minimal SessionABC protocol, composable wrappers
- [Mem0 Memory Layer](https://docs.mem0.ai/introduction) -- automatic extraction, reconciliation with existing memories
- [Context Engineering Compaction (Jason Liu)](https://jxnl.co/writing/2025/08/30/context-engineering-compaction/) -- raw > compaction > summarization hierarchy
- [Claude Code Memory](https://code.claude.com/docs/en/memory) -- MEMORY.md pattern, 200-line cap, topic files
