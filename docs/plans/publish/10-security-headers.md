---
title: "Security Headers Middleware"
status: completed
priority: P1
category: Security
date: 2026-02-22
---

# Security Headers Middleware

## Problem

No security headers (X-Content-Type-Options, X-Frame-Options, Content-Security-Policy, etc.). Browsers won't have basic protections against XSS, clickjacking, or MIME-sniffing attacks.

## Files to Change

- `src/agent_gateway/api/middleware/security.py` — New middleware
- `src/agent_gateway/gateway.py` — Register middleware
- `tests/test_integration/test_security_headers.py` — New test file

## Plan

1. Create `SecurityHeadersMiddleware` (pure ASGI, same pattern as `AuthMiddleware`):
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (configurable)
   - `Content-Security-Policy: default-src 'self'` (configurable, relaxed for dashboard)
   - `Referrer-Policy: strict-origin-when-cross-origin`
2. Add to Gateway startup (applied to all responses)
3. Make configurable via `SecurityConfig` in config.py (opt-out, not opt-in)
4. Add tests verifying headers on API and dashboard responses
5. Document in deployment guide
