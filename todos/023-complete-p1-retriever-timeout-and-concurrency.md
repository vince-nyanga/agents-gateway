---
status: pending
priority: p1
issue_id: "023"
tags: [code-review, performance, reliability]
dependencies: []
---

# Add timeout and concurrent execution for dynamic retrievers

## Problem Statement

In `_fetch_retriever_context` at `src/agent_gateway/workspace/prompt.py:84-96`:

1. **No timeout:** Each `retriever.retrieve()` call has no timeout. A slow or unresponsive retriever (network issue, overloaded vector DB) blocks prompt assembly indefinitely, stalling the user's request.

2. **Sequential execution:** Retrievers are called one-by-one in a `for` loop. If an agent has 3 retrievers each taking 500ms, total wait is 1500ms instead of 500ms with concurrent execution.

Both issues affect request latency and reliability in production.

## Findings

- **Location:** `src/agent_gateway/workspace/prompt.py:84-96`
- **Impact:** A single hung retriever stalls the entire request; multiple retrievers add latency linearly
- **The plan document** (line 161) explicitly mentions "Configurable per-retriever (default: 10s)" timeout but it was not implemented
- **Discovered by:** performance-oracle

## Proposed Solutions

### Solution A: `asyncio.gather` with `asyncio.wait_for` (Recommended)

```python
import asyncio

RETRIEVER_TIMEOUT_SECONDS = 10.0

async def _call_one(retriever, query: str, agent_id: str) -> list[str]:
    return await asyncio.wait_for(
        retriever.retrieve(query=query, agent_id=agent_id),
        timeout=RETRIEVER_TIMEOUT_SECONDS,
    )

async def _fetch_retriever_context(...) -> list[str]:
    retrievers = registry.resolve_for_agent(agent.retrievers)
    if not retrievers:
        return []
    tasks = [_call_one(r, query, agent.id) for r in retrievers]
    settled = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[str] = []
    for outcome in settled:
        if isinstance(outcome, Exception):
            logger.warning("Retriever failed for agent '%s'", agent.id, exc_info=outcome)
        else:
            results.extend(outcome)
    return results
```

- **Pros:** Concurrent execution, per-retriever timeout, clean error isolation
- **Cons:** Slightly more complex than sequential
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] Retrievers execute concurrently via `asyncio.gather`
- [ ] Each retriever call has a configurable timeout (default 10s per plan)
- [ ] Timeout and other failures are logged and gracefully skipped
- [ ] Tests cover timeout and concurrent execution scenarios

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #24 review | Always add timeouts for external I/O in request paths |

## Resources

- PR: #24
- Plan: `docs/plans/2026-02-20-feat-agent-rag-context-support-plan.md` (line 161 mentions timeout)
