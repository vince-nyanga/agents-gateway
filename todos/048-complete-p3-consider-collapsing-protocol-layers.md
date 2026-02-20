---
status: complete
priority: p3
issue_id: "048"
tags: [code-review, simplicity, architecture]
dependencies: []
---

# Consider Collapsing MemoryBackend + MemoryRepository Protocols

## Problem Statement
The two-layer protocol abstraction (`MemoryBackend` wrapping `MemoryRepository`) requires every backend to implement two classes. The `memory_repo` property is just indirection — `self._backend.memory_repo.save(...)` is a longer way to write `self._backend.save(...)`.

## Findings
- **Simplicity reviewer**: Highest-impact simplification opportunity
- Every backend implements 2 classes instead of 1
- ~40 LOC savings plus significant conceptual simplification

## Proposed Solutions

### Option A: Collapse into single MemoryBackend protocol
Single protocol with CRUD + lifecycle methods. Manager calls `self._backend.method()` directly.
- **Effort**: Large | **Risk**: Medium (breaking change for any early adopters)

### Option B: Keep current structure
Maintain separation for flexibility. Document the rationale.
- **Effort**: None | **Risk**: None

## Acceptance Criteria
- [ ] Decision made: collapse or keep
- [ ] If collapsing: all backends updated, tests pass
- [ ] If keeping: rationale documented

## Work Log
- 2026-02-20: Created from code review findings
