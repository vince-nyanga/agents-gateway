---
title: "Rate Limiting"
status: completed
priority: P1
category: Security
date: 2026-02-22
---

# Rate Limiting

## Problem

No rate limiting on any endpoint. A single client can overwhelm the service with requests, and auth endpoints are vulnerable to brute-force attacks. Businesses running this in production need basic protection.

## Files to Change

- `pyproject.toml` — Add `slowapi` as optional dependency
- `src/agent_gateway/config.py` — Add `RateLimitConfig`
- `src/agent_gateway/gateway.py` — Add rate limiting middleware
- `tests/test_integration/test_rate_limiting.py` — New test file

## Plan

1. Add `slowapi` as optional dependency under a `[rate-limiting]` extra and include in `[all]`
2. Add `RateLimitConfig` with sensible defaults:
   - `enabled: bool = False`
   - `default_limit: str = "100/minute"` (per IP)
   - `auth_limit: str = "10/minute"` (for auth-related endpoints)
3. Integrate `slowapi` Limiter in Gateway startup when enabled
4. Apply stricter limits to auth-sensitive paths
5. Add `429 Too Many Requests` response documentation
6. Add tests verifying rate limit enforcement and headers
7. Document configuration options
