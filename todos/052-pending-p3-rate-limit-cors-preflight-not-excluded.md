---
status: completed
priority: p3
issue_id: "052"
tags: [code-review, quality, rate-limiting, middleware]
dependencies: []
---

# CORS preflight (OPTIONS) requests are counted against the rate limit

## Problem Statement

In `gateway.py` the middleware wiring order (outermost first) is: auth → rate limiting → CORS. In ASGI middleware stacks the outermost layer handles requests first. This means CORS preflight OPTIONS requests pass through the rate limiter before reaching CORS middleware, consuming rate limit quota for browser pre-flight checks. A browser making many CORS-heavy API calls could exhaust its own rate limit with OPTIONS requests that never reach application logic.

## Findings

- **File**: `src/agent_gateway/gateway.py:607-668`
- Wiring order (lines 607–668): CORS added first (step 10b), rate limiting second (step 10c), auth third (step 11)
- In a wrapping middleware stack, the last one added becomes the outermost (first to receive requests)
- Auth wraps rate limiting, which wraps CORS
- OPTIONS requests: hit auth (pass — OPTIONS is not excluded by default), hit rate limiter (counted), reach CORS (responded)
- No explicit exclusion of OPTIONS from rate limiting

## Proposed Solutions

### Option A: Wire CORS before rate limiting in the stack (swap steps 10b and 10c)
Ensures CORS preflight short-circuits before the rate limiter sees the request.
- **Effort**: Small
- **Risk**: Low

### Option B: Accept current behavior — document it
CORS preflights are typically infrequent (browsers cache them). Document the behavior. Only a problem at very low rate limits.
- **Effort**: Minimal
- **Risk**: None to code

### Option C: Exempt OPTIONS method in the rate limiter key function
Return a synthetic unlimited key for OPTIONS requests.
- **Effort**: Small
- **Risk**: Low

## Recommended Action

_Leave blank — to be filled during triage._

## Technical Details

- **Affected files**: `src/agent_gateway/gateway.py`

## Acceptance Criteria

- [ ] CORS preflight requests do not consume rate limit quota, OR behavior is explicitly documented

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-23 | Created from rate limiting implementation review | |

## Resources

- `src/agent_gateway/gateway.py:607-668`
