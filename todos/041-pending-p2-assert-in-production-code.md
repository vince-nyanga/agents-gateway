---
status: pending
priority: p2
issue_id: "041"
tags: [code-review, quality, defensive-coding]
dependencies: []
---

# Assert in Production Code — Stripped by -O Flag

## Problem Statement
`gateway.py:404` uses `assert self._llm_client is not None` for a runtime guard. Asserts are stripped when Python runs with `-O` (optimize) flag, making this check vanish in production.

## Findings
- **Python reviewer**: P3 but important for correctness
- Should be a proper conditional guard with logging

## Proposed Solutions

### Option A: Replace with proper guard (Recommended)
```python
if self._llm_client is None:
    logger.warning("Memory requires LLM client, skipping memory init")
else:
    self._memory_manager = MemoryManager(...)
```
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] Assert replaced with proper conditional
- [ ] Warning logged when LLM client missing
- [ ] Memory gracefully skipped without LLM
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
