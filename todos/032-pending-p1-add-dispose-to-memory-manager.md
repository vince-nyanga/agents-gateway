---
status: pending
priority: p1
issue_id: "032"
tags: [code-review, architecture, encapsulation]
dependencies: []
---

# Add dispose() to MemoryManager — Private Attribute Access in Shutdown

## Problem Statement
`Gateway._shutdown()` at `gateway.py:591` accesses `self._memory_manager._backend.dispose()`, reaching into a private attribute. If `MemoryManager` restructures its internals, this breaks silently. The lifecycle contract is incomplete.

## Findings
- **Python reviewer**: P1 — maintenance hazard, incomplete lifecycle
- **Architecture reviewer**: P1 — private attribute access across class boundary
- **Agent-native reviewer**: Warning — should expose public `dispose()`

## Proposed Solutions

### Option A: Add public dispose() to MemoryManager (Recommended)
```python
# In manager.py
async def dispose(self) -> None:
    await self._backend.dispose()

# In gateway.py _shutdown
await self._memory_manager.dispose()
```
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] `MemoryManager.dispose()` method added
- [ ] `Gateway._shutdown()` uses public method
- [ ] No private attribute access across class boundaries
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
