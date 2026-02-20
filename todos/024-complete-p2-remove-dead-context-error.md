---
status: pending
priority: p2
issue_id: "024"
tags: [code-review, simplicity, yagni]
dependencies: []
---

# Remove unused `ContextError` exception class

## Problem Statement

`ContextError` is defined in `src/agent_gateway/exceptions.py:65-70` with a `retriever_name` field, but it is never raised or caught anywhere in the codebase. All retriever and context file failures use `logger.warning` with graceful skipping. This is dead code that creates a false promise in the exception hierarchy.

## Findings

- **Location:** `src/agent_gateway/exceptions.py:65-70`
- **No raise sites:** Grep for `ContextError` shows only the definition and the `__init__.py` import
- **Design:** All error handling correctly uses warn-and-skip pattern
- **Discovered by:** kieran-python-reviewer, code-simplicity-reviewer

## Proposed Solutions

### Solution A: Remove it (Recommended)

Delete `ContextError` from `exceptions.py` and remove any imports. Add it back if/when a concrete need arises.

- **Effort:** Small
- **Risk:** None

## Acceptance Criteria

- [ ] `ContextError` removed from `exceptions.py`
- [ ] All imports of `ContextError` removed
- [ ] Tests still pass
