---
status: pending
priority: p3
issue_id: "118"
tags: [code-review, testing, introspection]
dependencies: []
---

# memory_enabled parity fix in get_agent is untested

## Problem Statement

This PR includes an incidental parity fix: `GET /v1/agents/{id}` (`get_agent()`) was
not returning `memory_enabled` in its `AgentInfo` response, while `GET /v1/agents`
(`list_agents()`) was. The fix is correct — `memory_enabled=bool(...)` is now passed in
both places — but no test asserts that `get_agent` returns `memory_enabled`.

If the fix were reverted, no existing test would catch the regression.

## Findings

- `src/agent_gateway/api/routes/introspection.py` line 125: `memory_enabled` now present.
- `src/agent_gateway/api/routes/introspection.py` line 79: `memory_enabled` present in
  `list_agents` (was already there before this PR).
- `grep -rn "memory_enabled" tests/` returns no results — this field is not tested at all.

## Proposed Solutions

### Option A: Add test in TestIntrospectionOutputSchema (recommended)

In `tests/test_integration/test_output_schema.py`, add an assertion to the existing
`test_get_agent_includes_output_schema`:

```python
# memory_enabled is returned (parity fix verified)
assert "memory_enabled" in data
assert isinstance(data["memory_enabled"], bool)
```

**Pros:** Tiny, co-located with the output_schema test for the same endpoint.
**Cons:** None.
**Effort:** Trivial.

### Option B: Add a standalone introspection test file

Create `tests/test_api/test_introspection.py` with comprehensive tests for all
`AgentInfo` fields. More complete but larger scope.

**Effort:** Medium.

## Recommended Action

Option A — add two assertions in the existing test.

## Technical Details

- **Affected files:** `src/agent_gateway/api/routes/introspection.py`,
  `tests/test_integration/test_output_schema.py`.

## Acceptance Criteria

- [ ] A test asserts that `GET /v1/agents/{id}` response contains `memory_enabled` field.
- [ ] Test passes with `uv run pytest tests/test_integration/test_output_schema.py -v`.

## Work Log

- 2026-04-21: Identified during output_schema feature code review.
