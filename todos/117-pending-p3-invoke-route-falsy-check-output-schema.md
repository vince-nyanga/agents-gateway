---
status: pending
priority: p3
issue_id: "117"
tags: [code-review, quality, output-schema]
dependencies: []
---

# invoke.py uses falsy `or` check instead of `is not None` for output_schema override

## Problem Statement

In `src/agent_gateway/api/routes/invoke.py` line ~158, the per-call output_schema
override uses Python's `or` operator (falsy short-circuit):

```python
effective_output_schema = body.options.output_schema or (
    agent._pydantic_output_model or agent.output_schema
)
```

An empty dict `{}` is falsy in Python. If a caller sends `"output_schema": {}` in the
request body (a valid JSON Schema meaning "no constraints"), it is silently treated as
`None` and the agent's frontmatter schema wins instead of the caller's empty-schema
override.

The other two sites (`gateway.py` and `worker.py`) correctly use `is None`:

```python
# gateway.py (correct)
if options.output_schema is None:
    options.output_schema = agent._pydantic_output_model or agent.output_schema

# worker.py (correct)
if effective_output_schema is None:
    effective_output_schema = agent._pydantic_output_model or agent.output_schema
```

## Findings

- `src/agent_gateway/api/routes/invoke.py` line 158: falsy `or` check.
- `src/agent_gateway/gateway.py` line ~2702: correct `is None` check.
- `src/agent_gateway/queue/worker.py` line ~218: correct `is None` check.
- `src/agent_gateway/api/models.py` `InvokeOptions.output_schema` is typed
  `dict[str, Any] | None`, so only a dict (potentially `{}`) or `None` can arrive via HTTP.
- In practice, no real caller would send `{}` to mean "no schema", but the inconsistency
  is surprising and could mask bugs.

## Proposed Solutions

### Option A: Use explicit None check (recommended)

```python
effective_output_schema = (
    body.options.output_schema
    if body.options.output_schema is not None
    else (agent._pydantic_output_model or agent.output_schema)
)
```

**Pros:** Consistent with the other two sites; semantically correct.
**Cons:** Slightly more verbose.
**Effort:** Trivial.

### Option B: Leave as-is

`{}` is not a meaningful caller input and will never arrive from a real API client.

**Pros:** No change needed.
**Cons:** Three sites should be consistent; future reviewers will be confused by the asymmetry.

## Recommended Action

Option A — one-line fix for consistency.

## Technical Details

- **Affected file:** `src/agent_gateway/api/routes/invoke.py` line ~158.
- **Not a security issue** — only affects precedence resolution for a pathological input.

## Acceptance Criteria

- [ ] `invoke.py` uses `is not None` to check `body.options.output_schema`.
- [ ] All three precedence sites are consistent.

## Work Log

- 2026-04-21: Identified during output_schema feature code review.
