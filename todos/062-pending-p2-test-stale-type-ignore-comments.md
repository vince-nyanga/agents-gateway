---
status: pending
priority: p2
issue_id: "062"
tags: [code-review, quality, mypy]
dependencies: []
---

# 17 stale `# type: ignore[arg-type]` comments + 1 wrong suppression code

## Problem Statement

Every `AsyncClient(... base_url="http://test"  # type: ignore[arg-type])` call in `tests/test_api/test_execution_routes.py` carries a suppression that mypy no longer needs. Running `uv run mypy` reports `[unused-ignore]` on all 17 occurrences. Additionally, line 251 carries a `# type: ignore[union-attr]` that suppresses the wrong error code — the actual mypy error there is `[attr-defined]`, so the intended suppression is completely ineffective.

## Findings

- **File**: `tests/test_api/test_execution_routes.py`
- **mypy output** (representative):
  ```
  line 67: error: Unused "type: ignore" comment  [unused-ignore]
  line 251: error: "Callable[...] has no attribute return_value"  [attr-defined]
  line 251: note: Error code "attr-defined" not covered by "type: ignore" comment
  ```
- Total: 17 unused `[arg-type]` suppressions + 1 wrong suppression on line 251.
- The `[unused-ignore]` errors cause `uv run mypy src/ tests/` to report 18 errors, which will block CI once the test directory is added to mypy's scope.

## Proposed Solutions

### Option A — Remove all stale suppressions; fix line 251 separately (recommended)
1. Strip `# type: ignore[arg-type]` from all `base_url=` lines.
2. For line 251 (`mock_queue.request_cancel.return_value = True`): configure the mock before casting (see todo 063) so no suppression is needed at all.

Effort: Small. Risk: None.

### Option B — Replace with `# type: ignore[unused-ignore]`
Suppress the new warning instead of fixing root cause. This is counter-productive.

## Recommended Action

Option A.

## Technical Details

- **Affected files**: `tests/test_api/test_execution_routes.py` (all `base_url=` lines and line 251)

## Acceptance Criteria

- [ ] `uv run mypy src/ tests/` reports zero `[unused-ignore]` errors in the file
- [ ] All 15 tests still pass

## Work Log

- 2026-02-23: Identified during PR #13 code review.
