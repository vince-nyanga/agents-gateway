---
status: pending
priority: p1
issue_id: "013"
tags: [code-review, type-safety, workflow]
dependencies: []
---

# Replace Any type aliases for ToolExecutorFn and LLMCompletionFn

## Problem Statement

`ToolExecutorFn = Any` and `LLMCompletionFn = Any` in `workflow.py` bypass all type checking on the two most critical callables in the workflow engine. Any misuse of these functions will silently pass mypy.

## Findings

- **Source**: kieran-python-reviewer, architecture-strategist, code-simplicity-reviewer
- **Severity**: P1 — CRITICAL (type safety gap on core interfaces)
- **File**: `src/agent_gateway/engine/workflow.py`

## Proposed Solutions

### Option A: Use typing.Protocol
Define Protocol classes with `__call__` signatures matching the actual function signatures.
- **Pros**: Full mypy checking, IDE autocomplete, self-documenting
- **Cons**: Slight verbosity
- **Effort**: Small
- **Risk**: Low

### Option B: Use Callable type hints
Use `Callable[[ResolvedTool, dict, ToolContext], Coroutine[Any, Any, Any]]` directly.
- **Pros**: Concise
- **Cons**: Less readable for complex signatures
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] `ToolExecutorFn` and `LLMCompletionFn` have proper type definitions
- [ ] `mypy` catches incorrect usage of these callables
- [ ] All existing tests pass without changes

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | Avoid Any aliases for core interfaces |

## Resources

- PR #22
