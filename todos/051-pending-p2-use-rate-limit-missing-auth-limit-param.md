---
status: completed
priority: p2
issue_id: "051"
tags: [code-review, quality, rate-limiting]
dependencies: ["050"]
---

# `use_rate_limit()` fluent API does not expose `auth_limit`

## Problem Statement

`use_rate_limit()` in `gateway.py:1202` accepts `default_limit`, `storage_uri`, and `trust_forwarded_for` — but not `auth_limit`. Every other fluent config method (`use_cors`, `use_dashboard`) mirrors all configurable fields. The asymmetry means users relying solely on the Python API cannot set `auth_limit` without falling back to `gateway.yaml`. This is linked to todo #050 (the field may be removed), but if the field is kept, this method must be updated too.

## Findings

- **File**: `src/agent_gateway/gateway.py:1202-1224`
- `use_cors()` exposes all `CorsConfig` fields; `use_rate_limit()` skips `auth_limit`
- `RateLimitConfig` has 5 fields; `use_rate_limit()` only surfaces 3

## Proposed Solutions

### Option A: Add `auth_limit` parameter to `use_rate_limit()` (if field is kept)
```python
def use_rate_limit(
    self,
    *,
    default_limit: str = "100/minute",
    auth_limit: str = "10/minute",
    storage_uri: str | None = None,
    trust_forwarded_for: bool = False,
) -> Gateway:
```
- **Effort**: Small
- **Risk**: Low

### Option B: Remove `auth_limit` from config entirely (preferred if todo #050 chooses Option A)
No change needed here; the API stays consistent with the remaining fields.
- **Effort**: None (resolved by #050)
- **Risk**: None

## Recommended Action

_Resolve after triage of #050 — the two are coupled._

## Technical Details

- **Affected files**: `src/agent_gateway/gateway.py`

## Acceptance Criteria

- [ ] The fluent `use_rate_limit()` API exposes all fields present in `RateLimitConfig`

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-23 | Created from rate limiting implementation review | |

## Resources

- `src/agent_gateway/gateway.py:1202`
- Todo #050
