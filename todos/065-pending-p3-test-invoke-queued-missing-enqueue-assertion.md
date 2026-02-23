---
status: pending
priority: p3
issue_id: "065"
tags: [code-review, quality, tests]
dependencies: []
---

# test_async_invoke_queued: no assertion that queue.enqueue() was called

## Problem Statement

`test_async_invoke_queued` verifies the 202 response body (`execution_id`, `poll_url`) but never asserts that `mock_queue.enqueue` was actually called. If the route silently fell back to the `asyncio.create_task` path (e.g. due to a regression in the `isinstance(gw._queue, NullQueue)` check), the test would still pass while the queue branch was silently broken.

## Findings

- **File**: `tests/test_api/test_execution_routes.py`, lines 303–320
- Missing: `mock_queue.enqueue.assert_called_once()`
- The `isinstance(gw._queue, NullQueue)` guard in production code is the branch this test is specifically exercising.

## Proposed Solutions

### Option A — Add enqueue assertion (recommended)
```python
assert resp.status_code == 202
body = resp.json()
assert "execution_id" in body
assert "poll_url" in body
mock_queue.enqueue.assert_called_once()
```

## Recommended Action

Option A.

## Technical Details

- **Affected files**: `tests/test_api/test_execution_routes.py`

## Acceptance Criteria

- [ ] `mock_queue.enqueue.assert_called_once()` (or `assert_awaited_once`) is present in the test
- [ ] Test still passes

## Work Log

- 2026-02-23: Identified during PR #13 code review.
