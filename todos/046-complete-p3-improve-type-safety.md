---
status: complete
priority: p3
issue_id: "046"
tags: [code-review, quality, type-safety]
dependencies: []
---

# Improve Type Safety — Manager.repo and make_memory_tools

## Problem Statement
`MemoryManager.repo` property returns `Any` (manager.py:83-85), opting out of type checking. `make_memory_tools` returns `list[dict[str, Any]]` which provides no type safety.

## Findings
- **Python reviewer**: P2 — type safety gaps
- **Architecture reviewer**: P3 — imprecise return types

## Proposed Solutions

### Option A: Use proper types (Recommended)
- `MemoryManager.repo` → return `MemoryRepository`
- `make_memory_tools` → return `list[ToolDescriptor]` using a TypedDict
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] Manager.repo properly typed as MemoryRepository
- [ ] make_memory_tools uses TypedDict or proper type
- [ ] mypy passes
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
