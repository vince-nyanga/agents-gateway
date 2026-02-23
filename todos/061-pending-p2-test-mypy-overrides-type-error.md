---
status: pending
priority: p2
issue_id: "061"
tags: [code-review, quality, mypy]
dependencies: []
---

# _make_record **overrides typed as `object` causes mypy arg-type error

## Problem Statement

`_make_record` in `tests/test_api/test_execution_routes.py` declares `**overrides: object`, but then calls `fields.update(overrides)` where `fields` is `dict[str, str]`. mypy strict mode rejects this because `dict[str, object]` is not assignable to the mapping expected by `dict.update`. This is one of the 18 mypy errors reported when running `mypy src/` (mypy checks tests when they import from src).

## Findings

- **File**: `tests/test_api/test_execution_routes.py`, lines 37–45
- **mypy output**: `error: Argument 1 to "update" of "MutableMapping" has incompatible type "dict[str, object]"; expected "SupportsKeysAndGetItem[str, str]"  [arg-type]`
- Root cause: `**overrides: object` is too restrictive for a helper that is passing arbitrary `ExecutionRecord` field values.

```python
def _make_record(
    execution_id: str = "exec-1",
    agent_id: str = "test-agent",
    status: str = "completed",
    **overrides: object,          # <-- should be Any
) -> ExecutionRecord:
    fields = dict(
        id=execution_id,
        agent_id=agent_id,
        status=status,
        message="hello",
    )
    fields.update(overrides)      # mypy error here
```

## Proposed Solutions

### Option A — Change annotation to `Any` (recommended)
```python
from typing import Any
def _make_record(..., **overrides: Any) -> ExecutionRecord:
```
Pros: Correct, idiomatic for test helpers. No runtime change.
Effort: Small. Risk: None.

### Option B — Use `cast`
```python
fields.update(cast(dict[str, Any], overrides))
```
Pros: Keeps the `object` annotation as a hint.
Cons: More verbose; cast in test helpers is unusual noise.
Effort: Small. Risk: None.

## Recommended Action

Option A.

## Technical Details

- **Affected files**: `tests/test_api/test_execution_routes.py`
- **Components**: test helpers

## Acceptance Criteria

- [ ] `uv run mypy src/ tests/` reports no `[arg-type]` error on line 44
- [ ] `uv run pytest tests/test_api/ -x -q` still passes

## Work Log

- 2026-02-23: Identified during PR #13 code review.
