---
status: complete
priority: p3
issue_id: "019"
tags: [code-review, simplicity, resolver]
dependencies: []
---

# Inline _split_path helper in resolver.py

## Problem Statement

`_split_path()` is a trivial one-line wrapper around `path.split(".")`. It adds indirection without value.

## Findings

- **Source**: code-simplicity-reviewer
- **File**: `src/agent_gateway/engine/resolver.py`

## Acceptance Criteria

- [ ] `_split_path` removed, callers use `path.split(".")` directly
- [ ] All tests pass

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | |
