---
title: "feat: Add RAG Context Support for Agents"
type: feat
status: completed
date: 2026-02-20
---

# feat: Add RAG Context Support for Agents

## Overview

Add Retrieval-Augmented Generation (RAG) support for agents through two complementary mechanisms: **static context files** (markdown documents that provide reference material) and **dynamic retrievers** (a protocol for fetching context at runtime). This enables agents to access domain knowledge, style guides, example documents, and live data without using the tool system.

## Problem Statement / Motivation

Agents currently receive instructions via their `AGENT.md` prompt and skill instructions, but have no way to access supplementary reference material. For example:

- An email-drafting agent needs example emails to learn tone and style
- A support agent needs access to a knowledge base of FAQs
- A code-review agent needs project-specific conventions that change over time

Embedding all this in `AGENT.md` is impractical — it mixes instructions with reference data, makes files huge, and doesn't support dynamic content. RAG context solves this by separating **what the agent knows** from **what the agent does**.

This is explicitly distinct from tools: tools let agents take actions; context lets agents access knowledge.

## Proposed Solution

### Static Context Files

Markdown files placed alongside an agent provide reference material injected into the system prompt at assembly time.

**Auto-discovery:** Files in `workspace/agents/<name>/context/*.md` are automatically loaded.

```
workspace/agents/email-drafter/
├── AGENT.md
├── BEHAVIOR.md
└── context/
    ├── 01-tone-guide.md
    ├── 02-example-emails.md
    └── 03-signature-templates.md
```

**Explicit references:** Additional files can be listed in AGENT.md frontmatter, resolved relative to the workspace root:

```yaml
---
description: Drafts professional emails
context:
  - shared/company-style-guide.md
  - shared/brand-voice.md
---
```

Both mechanisms can be used together. Files from `context/` are loaded in alphabetical order.

### Dynamic Retrievers

A Python protocol (abstract base class) for fetching context at runtime. Implementers register named retrievers on the Gateway, and agents reference them by name.

**Protocol:**

```python
# src/agent_gateway/context/protocol.py

class ContextRetriever(Protocol):
    async def retrieve(
        self,
        *,
        query: str,
        agent_id: str,
    ) -> list[str]:
        """Retrieve context chunks relevant to the query for the given agent."""
        ...

    async def initialize(self) -> None:
        """Called once during Gateway startup. Set up connections, load indices, etc."""
        ...

    async def close(self) -> None:
        """Called during Gateway shutdown. Clean up resources."""
        ...
```

**Registration (follows pending pattern):**

```python
from agent_gateway import Gateway

gw = Gateway()

gw.use_retriever("vector-search", PineconeRetriever(index="support-kb"))
gw.use_retriever("web-search", WebSearchRetriever(api_key="..."))
```

**Agent configuration:**

```yaml
---
description: Customer support agent
retrievers:
  - vector-search
---
```

**Runtime:** During prompt assembly, each retriever is called with the user's query and agent ID. Results are injected as a context layer in the system prompt.

## Technical Considerations

### Prompt Assembly Layer Order

The current layer order in `workspace/prompt.py` is:

1. Date/time
2. Root system prompt (`AGENTS.md`)
3. Root behavior (`BEHAVIOR.md`)
4. Agent prompt (`AGENT.md` body)
5. Agent behavior (`BEHAVIOR.md`)
6. Skill instructions

RAG context is inserted as **layer 5.5** — after agent behavior, before skills:

1. Date/time
2. Root system prompt
3. Root behavior
4. Agent prompt
5. Agent behavior
6. **Static context files** (wrapped in a `## Reference Material` section)
7. **Dynamic retriever results** (wrapped in a `## Retrieved Context` section)
8. Skill instructions

### Async Prompt Assembly

`assemble_system_prompt()` must become async to support retriever calls. This affects:

- `src/agent_gateway/engine/executor.py` — `_build_messages()` call site
- `src/agent_gateway/gateway.py` — `chat()` method prompt assembly

Both callers are already in async contexts, so this is a straightforward change.

### Static Context Loading

Static context files are read at **workspace load time** (in `AgentDefinition.load()` or the loader), not at prompt assembly time. This means:

- No disk I/O during request handling
- Files are refreshed on `reload()`
- Content is stored on the `AgentDefinition` dataclass

### Cross-Reference Validation

The existing `_validate_cross_references()` in `loader.py` will be extended to:

- Warn if an agent references a `retriever` name that isn't registered
- Warn if explicit `context:` paths don't resolve to existing files
- Apply `_is_safe_entry()` style path safety checks to context file paths (prevent path traversal)

### Error Handling

- **Static file not found:** Warning logged, agent loads without that context file
- **Retriever exception:** Warning logged, prompt assembled without that retriever's results. Execution continues.
- **Retriever timeout:** Configurable per-retriever (default: 10s). On timeout, same as exception.

### Relation to `GatewayConfig.context`

The existing `context: dict[str, Any]` in `config.py` provides gateway-wide key-value business context. RAG context is orthogonal — it provides per-agent document-level reference material. No naming collision in the config; the AGENT.md frontmatter key `context:` refers to static file paths.

### On-Demand Retrieval (Future)

The v1 implementation calls retrievers at prompt assembly time only. On-demand retrieval during execution (e.g., mid-conversation re-retrieval) is deferred to a future iteration once the trigger mechanism is designed.

## Acceptance Criteria

### Static Context

- [x] Files in `workspace/agents/<name>/context/*.md` are auto-discovered and loaded
- [x] Explicit `context:` list in AGENT.md frontmatter resolves files relative to workspace root
- [x] Static context appears in the assembled system prompt after agent behavior
- [x] Files are loaded alphabetically within the `context/` directory
- [x] Only `.md` files are loaded (others ignored with a debug log)
- [x] Path traversal and symlink attacks are prevented
- [x] Context files are refreshed on `reload()`
- [x] Missing explicit context files produce a warning, not an error

### Dynamic Retrievers

- [x] `ContextRetriever` protocol defined with `retrieve()`, `initialize()`, `close()`
- [x] `gw.use_retriever(name, instance)` registers a retriever (pre-startup only)
- [x] `_pending_retrievers` applied during `_startup()` and `reload()`
- [x] Retrievers referenced by name in AGENT.md frontmatter via `retrievers:` key
- [x] `assemble_system_prompt()` is async, calls retrievers with query + agent_id
- [x] Retriever results injected into prompt after static context, before skills
- [x] Cross-reference validation warns on unknown retriever names
- [x] Retriever failures are logged and gracefully skipped
- [x] `initialize()` called during startup, `close()` during shutdown
- [x] Duplicate retriever names raise an error at registration time

### Testing

- [x] Unit tests for static context loading (auto-discovery + explicit)
- [x] Unit tests for retriever registration and resolution
- [x] Unit tests for prompt assembly with context layers
- [x] Unit tests for error cases (missing files, failing retrievers, path traversal)
- [x] Example project updated with a static-context agent and a retriever-based agent

## Success Metrics

- Agents can reference static knowledge without bloating AGENT.md
- Custom retrieval logic (vector DB, HTTP, etc.) integrates via a clean protocol
- Zero impact on agents that don't use RAG (no performance regression)
- Retriever failures never crash agent execution

## Dependencies & Risks

**Dependencies:**
- No new external dependencies for the core feature
- Implementers bring their own retriever backends (pinecone, pgvector, etc.)

**Risks:**
- **Context window overflow:** Large context files or verbose retriever results can exceed LLM limits. Mitigation: log a warning when total prompt size exceeds a configurable threshold (default: 50,000 chars). Token budget management is a follow-up optimization.
- **Prompt injection via retrieved content:** External retriever results could contain adversarial instructions. Mitigation: wrap retrieved content in clear delimiters (`## Retrieved Context` / `---`) so the LLM can distinguish instructions from reference material. Full sanitization is a follow-up.
- **Async migration:** Making `assemble_system_prompt()` async touches multiple callers. Mitigation: both callers are already async, so the change is mechanical.

## Implementation Files

### New Files

| File | Purpose |
|---|---|
| `src/agent_gateway/context/__init__.py` | Package init, exports protocol |
| `src/agent_gateway/context/protocol.py` | `ContextRetriever` protocol definition |
| `src/agent_gateway/context/registry.py` | `RetrieverRegistry` — maps names to instances, resolves for agents |
| `tests/test_context/test_protocol.py` | Protocol conformance tests |
| `tests/test_context/test_registry.py` | Registry unit tests |
| `tests/test_context/test_static_context.py` | Static file loading tests |
| `tests/test_context/test_prompt_integration.py` | Prompt assembly with context |

### Modified Files

| File | Change |
|---|---|
| `src/agent_gateway/workspace/agent.py` | Add `context_files: list[str]`, `context_content: list[str]`, `retrievers: list[str]` to `AgentDefinition`; parse from frontmatter; load `context/` dir |
| `src/agent_gateway/workspace/loader.py` | Load context files during agent loading; validate context paths; add retriever cross-reference validation |
| `src/agent_gateway/workspace/prompt.py` | Make `assemble_system_prompt()` async; add static context and retriever result layers |
| `src/agent_gateway/gateway.py` | Add `_pending_retrievers`, `use_retriever()`, apply in `_startup()`/`reload()`, call `initialize()`/`close()` |
| `src/agent_gateway/engine/executor.py` | Await async `assemble_system_prompt()`, pass query to prompt assembly |
| `src/agent_gateway/exceptions.py` | Add `ContextError` subclass |
| `examples/test-project/` | Add demo agent with static context + retriever example |

## References & Research

### Internal References

- Pending registration pattern: `src/agent_gateway/gateway.py:88` (`_pending_tools`)
- Prompt assembly: `src/agent_gateway/workspace/prompt.py:12` (`assemble_system_prompt`)
- Agent definition: `src/agent_gateway/workspace/agent.py:39` (`AgentDefinition`)
- Workspace loader: `src/agent_gateway/workspace/loader.py:48` (`load_workspace`)
- Cross-reference validation: `src/agent_gateway/workspace/loader.py:177`
- Path safety: `src/agent_gateway/workspace/loader.py:93` (`_is_safe_entry`)
- Tool registry (reference pattern): `src/agent_gateway/workspace/registry.py`
- Executor message building: `src/agent_gateway/engine/executor.py:140`
