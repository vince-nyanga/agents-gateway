---
status: pending
priority: p2
issue_id: "042"
tags: [code-review, quality, dry]
dependencies: []
---

# Duplicate Memory Block Logic in invoke() and chat()

## Problem Statement
Memory block retrieval logic is duplicated between `invoke()` (lines 1356-1369) and `chat()` (lines 1460-1473) in `gateway.py`. Both do the same null checks and `get_context_block()` call.

## Findings
- **Python reviewer**: P3 — DRY violation
- **Architecture reviewer**: P3 — duplicated code
- **Simplicity reviewer**: flagged as dedup opportunity

## Proposed Solutions

### Option A: Extract private helper (Recommended)
```python
async def _get_memory_block(self, agent_id: str, agent: AgentDefinition, message: str) -> str:
    if self._memory_manager is None:
        return ""
    agent_mem = agent.memory_config
    if not agent_mem or not agent_mem.enabled:
        return ""
    try:
        return await self._memory_manager.get_context_block(
            agent_id, query=message, max_chars=agent_mem.max_injected_chars,
        )
    except Exception:
        logger.warning("Failed to fetch memory for agent '%s'", agent_id, exc_info=True)
        return ""
```
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] Memory block logic extracted to single method
- [ ] Both invoke() and chat() use the helper
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
