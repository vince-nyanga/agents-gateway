---
status: completed
priority: p2
issue_id: "050"
tags: [code-review, quality, rate-limiting]
dependencies: []
---

# `auth_limit` in RateLimitConfig is dead code

## Problem Statement

`RateLimitConfig.auth_limit` (`config.py:267`) is defined with a default of `"10/minute"` and is documented in `docs/api-reference/configuration.md`, but it is never read by `setup_rate_limiting()`, never passed to the `Limiter` constructor, and never applied as a per-route decorator. Users who set `rate_limit.auth_limit` in `gateway.yaml` will believe auth endpoints are protected by a tighter limit, but nothing enforces it. This is misleading and creates silent misconfiguration risk.

## Findings

- **File**: `src/agent_gateway/config.py:267`
- **File**: `src/agent_gateway/ratelimit.py` — `setup_rate_limiting()` only passes `config.default_limit` to `Limiter(default_limits=[...])`
- **File**: `src/agent_gateway/gateway.py:1202-1224` — `use_rate_limit()` does not expose `auth_limit` at all
- **File**: `docs/api-reference/configuration.md:289` — documents it as "Reserved for future per-auth-route limiting"
- Confirmed via grep: zero call-sites consume `auth_limit`

## Proposed Solutions

### Option A: Remove the field (Recommended)
Remove `auth_limit` from `RateLimitConfig` and from the docs table. Add a note in the docs that per-route limits can be applied in future via `@limiter.limit()` decorators.
- **Effort**: Small
- **Risk**: Low — it is a config field with no runtime effect, so removing it is non-breaking

### Option B: Wire it to auth-related route handlers
Apply `@limiter.limit(config.auth_limit)` to the token/auth endpoints. This requires identifying those routes and decorating them, which is non-trivial given the dynamic route registration pattern.
- **Effort**: Medium
- **Risk**: Medium — need to ensure the limiter instance is accessible at route decoration time

### Option C: Keep as a documented reserved field
Rename to `_auth_limit` or add a prominent `# NOT YET IMPLEMENTED` comment, and update docs to clearly say "reserved for future use — has no effect".
- **Effort**: Small
- **Risk**: Low

## Recommended Action

_Leave blank — to be filled during triage._

## Technical Details

- **Affected files**: `src/agent_gateway/config.py`, `src/agent_gateway/ratelimit.py`, `docs/api-reference/configuration.md`

## Acceptance Criteria

- [ ] Either `auth_limit` is wired to enforce limits on auth routes, OR it is removed and docs updated
- [ ] No user-visible config field exists that silently has no effect

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-23 | Created from rate limiting implementation review | |

## Resources

- `src/agent_gateway/config.py`
- `src/agent_gateway/ratelimit.py`
- `docs/api-reference/configuration.md`
