---
status: pending
priority: p2
issue_id: "063"
tags: [code-review, quality, mypy, mocks]
dependencies: []
---

# test_cancel_via_queue: cast before configuring mock silences mypy incorrectly

## Problem Statement

`test_cancel_via_queue` casts an `AsyncMock` to `ExecutionQueue` before setting `mock_queue.request_cancel.return_value = True`. Because mypy sees the cast type (the protocol), it reports `[attr-defined]` — the protocol's method has no `.return_value`. The `# type: ignore[union-attr]` comment present does NOT cover `[attr-defined]`, so the error is still emitted. This means mypy strict mode fails silently on a genuine mock-wiring bug pattern.

## Findings

- **File**: `tests/test_api/test_execution_routes.py`, lines 248–261
- **mypy error**: `"Callable[[str], Coroutine[Any, Any, bool]]" has no attribute "return_value"  [attr-defined]`
- Current code:
  ```python
  mock_queue = cast("ExecutionQueue", AsyncMock())
  mock_queue.request_cancel.return_value = True   # [attr-defined] — not suppressed
  gw._queue = mock_queue
  ```
- The suppression `# type: ignore[union-attr]` on this line covers the wrong error code.

## Proposed Solutions

### Option A — Configure mock before casting (recommended)
```python
_raw_queue = AsyncMock()
_raw_queue.request_cancel.return_value = True
gw._queue = cast("ExecutionQueue", _raw_queue)
```
Pros: Type-safe pattern; no suppression needed; correct at runtime.
Effort: Small. Risk: None.

### Option B — Use `# type: ignore[attr-defined]`
Suppress with the correct error code. Avoids refactor but leaves the anti-pattern.
Effort: Trivial. Risk: None.

## Recommended Action

Option A — it's also the correct pattern for all future mock-then-cast usage in this test module.

## Technical Details

- **Affected files**: `tests/test_api/test_execution_routes.py`, lines 248–261
- **Pattern to standardize**: Always configure `AsyncMock` before `cast()`

## Acceptance Criteria

- [ ] `uv run mypy src/ tests/` reports no `[attr-defined]` error on line 251
- [ ] `test_cancel_via_queue` still passes and asserts `request_cancel` was called

## Work Log

- 2026-02-23: Identified during PR #13 code review.
