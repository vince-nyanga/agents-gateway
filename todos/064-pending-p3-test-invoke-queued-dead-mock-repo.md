---
status: pending
priority: p3
issue_id: "064"
tags: [code-review, quality, tests]
dependencies: []
---

# test_async_invoke_queued: mock_repo created but never wired or asserted

## Problem Statement

`test_async_invoke_queued` creates `mock_repo = AsyncMock(spec=NullExecutionRepository)` but never assigns it to `gw._execution_repo`. The test uses the live `NullExecutionRepository`. The mock is dead code — it pollutes the test without providing any value or protection.

## Findings

- **File**: `tests/test_api/test_execution_routes.py`, lines 305–308
- `mock_repo` is created but never used.
- Production `invoke_agent` calls `gw._execution_repo.create(record)` before enqueueing; the live null repo silently swallows this. The test neither verifies this call happened nor fails if it regresses.

## Proposed Solutions

### Option A — Wire the mock and add assertion (recommended)
```python
mock_repo = AsyncMock(spec=NullExecutionRepository)
gw._execution_repo = mock_repo
...
mock_repo.create.assert_called_once()
```

### Option B — Remove the dead variable
If verifying `create` is not important for this test's purpose, just delete the two lines.

## Recommended Action

Option A if the goal is full coverage; Option B if this test is intentionally narrow.

## Technical Details

- **Affected files**: `tests/test_api/test_execution_routes.py`

## Acceptance Criteria

- [ ] `mock_repo` is either wired and asserted, or removed entirely
- [ ] No dead variables remain in the test

## Work Log

- 2026-02-23: Identified during PR #13 code review.
