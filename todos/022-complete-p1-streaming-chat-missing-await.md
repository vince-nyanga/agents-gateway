---
status: pending
priority: p1
issue_id: "022"
tags: [code-review, regression, bug]
dependencies: []
---

# Streaming chat route missing `await` on async `assemble_system_prompt`

## Problem Statement

`assemble_system_prompt()` was converted from sync to async in this PR, but the call site in `_create_streaming_response` at `src/agent_gateway/api/routes/chat.py:159` was not updated. This means:

1. The function returns a coroutine object instead of the actual prompt string
2. The system prompt sent to the LLM in streaming mode will be `<coroutine object assemble_system_prompt at 0x...>`
3. RAG context (both static and dynamic) is never injected for streaming chat
4. This is a **silent regression** — no error is raised, the LLM just gets a broken prompt

## Findings

- **Location:** `src/agent_gateway/api/routes/chat.py:159`
- **Current code:** `system_prompt = assemble_system_prompt(agent, snapshot.workspace)`
- **Missing:** `await`, plus `query` and `retriever_registry` keyword arguments
- **Agents affected:** All agents using streaming chat, not just RAG-enabled ones
- **Discovered by:** kieran-python-reviewer

## Proposed Solutions

### Solution A: Fix the call site (Recommended)

```python
retriever_reg = snapshot.retriever_registry if snapshot else None
system_prompt = await assemble_system_prompt(
    agent,
    snapshot.workspace,
    query=body.message,
    retriever_registry=retriever_reg,
)
```

- **Pros:** Direct fix, minimal change
- **Cons:** None
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `assemble_system_prompt` is awaited in the streaming chat route
- [ ] `query` and `retriever_registry` are passed to the function
- [ ] Streaming chat works correctly for agents with and without RAG context
- [ ] Add a test for the streaming path if not already covered

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #24 review | Always grep all call sites when changing a function signature from sync to async |

## Resources

- PR: #24
- File: `src/agent_gateway/api/routes/chat.py:159`
