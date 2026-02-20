---
status: pending
priority: p2
issue_id: "043"
tags: [code-review, quality, consistency]
dependencies: []
---

# Cache NullMemoryBackend.memory_repo Instance

## Problem Statement
`NullMemoryBackend.memory_repo` at `null.py:65` creates a new `NullMemoryRepository()` on every property access. This is inconsistent with `FileMemoryBackend` which caches `self._repo`, and breaks identity checks.

## Findings
- **Python reviewer**: P2 — wasteful, inconsistent
- **Architecture reviewer**: P2 — diverges from other backends

## Proposed Solutions

### Option A: Cache in __init__ (Recommended)
```python
class NullMemoryBackend:
    def __init__(self):
        self._repo = NullMemoryRepository()

    @property
    def memory_repo(self):
        return self._repo
```
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] NullMemoryRepository cached in __init__
- [ ] Property returns same instance
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
