---
status: pending
priority: p1
issue_id: "031"
tags: [code-review, quality, naming]
dependencies: []
---

# Rename MemoryError — Shadows Python Builtin

## Problem Statement
`MemoryError` at `src/agent_gateway/exceptions.py:73` shadows Python's builtin `MemoryError` exception. Any code importing this class will mask the critical system exception for out-of-memory conditions, causing extremely confusing behavior.

## Findings
- **Python reviewer**: P1 — latent defect that can cause wrong exception type to be caught
- **Architecture reviewer**: P1 — naming hazard confirmed
- Affects: `exceptions.py`, `manager.py`, `config.py` imports, test files

## Proposed Solutions

### Option A: Rename to `AgentMemoryError` (Recommended)
- Follows project pattern of prefixing domain-specific exceptions
- Update all references: `MemoryBackendError(AgentMemoryError)`, `MemoryCompactionError(AgentMemoryError)`
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] `MemoryError` renamed to `AgentMemoryError` in exceptions.py
- [ ] All subclasses updated to inherit from `AgentMemoryError`
- [ ] All imports and references updated across codebase
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
