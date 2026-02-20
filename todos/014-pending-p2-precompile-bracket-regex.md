---
status: pending
priority: p2
issue_id: "014"
tags: [code-review, performance, resolver]
dependencies: []
---

# Pre-compile bracket regex in resolver _navigate()

## Problem Statement

The bracket pattern `r"^(.*)\[(\d+)\]$"` in `resolver.py:_navigate()` is compiled on every call. Should be a module-level constant like `_REF_PATTERN`.

## Findings

- **Source**: kieran-python-reviewer, performance-oracle, code-simplicity-reviewer
- **File**: `src/agent_gateway/engine/resolver.py`

## Proposed Solutions

### Option A: Move to module-level compiled constant
```python
_BRACKET_PATTERN = re.compile(r"^(.*)\[(\d+)\]$")
```
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] Bracket regex is pre-compiled at module level
- [ ] All resolver tests pass

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | |

## Resources

- PR #22
