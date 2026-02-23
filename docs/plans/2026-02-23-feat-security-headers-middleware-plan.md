---
title: "feat: Add Security Headers Middleware"
type: feat
status: active
date: 2026-02-23
---

# Security Headers Middleware

## Overview

Add a pure-ASGI `SecurityHeadersMiddleware` that injects standard security headers into every HTTP response. The middleware is **enabled by default** (opt-out, not opt-in) and configurable via `SecurityConfig` in `config.py` and a `use_security_headers()` fluent API on `Gateway`. This protects against XSS, clickjacking, MIME-sniffing, and other browser-based attacks out of the box.

## Problem Statement

The gateway currently sends no security headers. Browsers lack basic protections against XSS, clickjacking, and MIME-sniffing. Every production deployment must add these manually via a reverse proxy or custom middleware. This should be built in.

## Proposed Solution

Follow the exact same integration pattern as CORS (`CorsConfig` + `_pending_cors_config` + `use_cors()` + wiring in `_do_startup`), but with `enabled: True` by default. The middleware itself follows the `AuthMiddleware` pure-ASGI pattern (no `BaseHTTPMiddleware` dependency).

The middleware intercepts `http.response.start` messages and injects headers. For dashboard paths (`/dashboard/`), the CSP is relaxed to allow inline styles/scripts needed by the UI.

## Files to Create or Modify

### New Files

1. **`src/agent_gateway/api/middleware/security.py`** -- The middleware class
2. **`tests/test_integration/test_security_headers.py`** -- Integration tests
3. **`docs/guides/security-headers.md`** -- User guide

### Modified Files

4. **`src/agent_gateway/config.py`** -- Add `SecurityConfig` model + field on `GatewayConfig`
5. **`src/agent_gateway/gateway.py`** -- Add `_pending_security_config`, `use_security_headers()`, wiring in `_do_startup`
6. **`examples/test-project/workspace/gateway.yaml`** -- Add `security` section
7. **`examples/test-project/app.py`** -- Add `gw.use_security_headers()` call
8. **`docs/guides/configuration.md`** -- Add `security` section
9. **`docs/api-reference/configuration.md`** -- Add `SecurityConfig` reference
10. **`docs/api-reference/gateway.md`** -- Add `use_security_headers()` method
11. **`docs/llms.txt`** -- Add security headers mention
12. **`mkdocs.yml`** -- Add `Security Headers` to nav under Guides

## Implementation Steps

### Step 1: Add `SecurityConfig` to `src/agent_gateway/config.py`

Add a new Pydantic `BaseModel` after `RateLimitConfig` (line ~269):

```python
class SecurityConfig(BaseModel):
    enabled: bool = True  # opt-out, not opt-in
    x_content_type_options: str = "nosniff"
    x_frame_options: str = "DENY"
    strict_transport_security: str = "max-age=31536000; includeSubDomains"
    content_security_policy: str = "default-src 'self'"
    referrer_policy: str = "strict-origin-when-cross-origin"
    # Relaxed CSP for dashboard paths (needs inline styles/scripts)
    dashboard_content_security_policy: str = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self' data:"
    )
```

Add to `GatewayConfig` after `rate_limit`:

```python
security: SecurityConfig = SecurityConfig()
```

Add `SecurityConfig` to the imports in `gateway.py` (line ~26, alongside `CorsConfig`, `RateLimitConfig`).

### Step 2: Create `src/agent_gateway/api/middleware/security.py`

Pure ASGI middleware following the same pattern as `AuthMiddleware` at `src/agent_gateway/auth/middleware.py`. Key design:

```python
"""Pure ASGI security headers middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agent_gateway.config import SecurityConfig

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class SecurityHeadersMiddleware:
    """Inject standard security headers into every HTTP response.

    Intercepts ``http.response.start`` ASGI messages and appends
    security headers before forwarding to the inner application.
    Dashboard paths receive a relaxed Content-Security-Policy to
    allow inline styles/scripts required by the UI.
    """

    def __init__(self, app: ASGIApp, config: SecurityConfig) -> None:
        self.app = app
        self._config = config
        # Pre-encode headers for performance (called on every response)
        self._base_headers: list[tuple[bytes, bytes]] = [
            (b"x-content-type-options", config.x_content_type_options.encode()),
            (b"x-frame-options", config.x_frame_options.encode()),
            (b"referrer-policy", config.referrer_policy.encode()),
        ]
        if config.strict_transport_security:
            self._base_headers.append(
                (b"strict-transport-security", config.strict_transport_security.encode())
            )
        self._api_csp = config.content_security_policy.encode()
        self._dashboard_csp = config.dashboard_content_security_policy.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        is_dashboard = path.startswith("/dashboard")

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._base_headers)
                # Use relaxed CSP for dashboard, strict for API
                csp = self._dashboard_csp if is_dashboard else self._api_csp
                headers.append((b"content-security-policy", csp))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
```

**Key decisions:**
- Pre-encode headers in `__init__` to avoid per-request encoding overhead.
- Dashboard detection is path-based (`/dashboard`), matching the existing dashboard mount point.
- HSTS header is conditionally added (empty string disables it, useful for non-TLS dev).
- The middleware wraps the `send` callable to intercept `http.response.start`, same approach used by Starlette's own middleware.

### Step 3: Wire into `src/agent_gateway/gateway.py`

**3a. Add pending attribute in `__init__`** (after `_pending_rate_limit_config`, line ~147):

```python
self._pending_security_config: SecurityConfig | None = None  # fluent API
```

**3b. Add import** to the import block at line ~26:

```python
from agent_gateway.config import (
    ...
    SecurityConfig,
)
```

**3c. Add wiring in `_do_startup`** -- insert **before** the CORS block (before line 607), so security headers are the outermost middleware (applied last in the wrapping chain, meaning first in the response path). This is step "10a":

```python
# 10a. Wire security headers middleware if enabled
if self._pending_security_config is not None:
    self._config.security = self._pending_security_config
if self._config.security.enabled:
    from agent_gateway.api.middleware.security import SecurityHeadersMiddleware

    if self.middleware_stack is not None:
        self.middleware_stack = SecurityHeadersMiddleware(
            app=self.middleware_stack,
            config=self._config.security,
        )
    else:
        self.add_middleware(SecurityHeadersMiddleware, config=self._config.security)
```

**Ordering rationale:** Security headers should wrap outermost so they are added to *all* responses, including CORS preflight responses, auth 401 responses, and rate-limit 429 responses. Since middleware wrapping is inside-out, adding it *before* CORS/rate-limit/auth in the startup code means it wraps outside all of them.

**3d. Add fluent API method** after `use_rate_limit` (around line 1224):

```python
# --- Security headers configuration (fluent API) ---

def use_security_headers(
    self,
    *,
    x_content_type_options: str = "nosniff",
    x_frame_options: str = "DENY",
    strict_transport_security: str = "max-age=31536000; includeSubDomains",
    content_security_policy: str = "default-src 'self'",
    referrer_policy: str = "strict-origin-when-cross-origin",
    dashboard_content_security_policy: str | None = None,
) -> Gateway:
    """Customize security headers.

    Security headers are enabled by default. Use this method to override
    individual header values. To disable entirely, set ``security.enabled: false``
    in gateway.yaml.

    Example::

        gw = Gateway(workspace="workspace/")
        gw.use_security_headers(x_frame_options="SAMEORIGIN")
    """
    if self._started:
        raise RuntimeError(
            "Cannot configure security headers after gateway has started"
        )
    kwargs: dict[str, Any] = {
        "enabled": True,
        "x_content_type_options": x_content_type_options,
        "x_frame_options": x_frame_options,
        "strict_transport_security": strict_transport_security,
        "content_security_policy": content_security_policy,
        "referrer_policy": referrer_policy,
    }
    if dashboard_content_security_policy is not None:
        kwargs["dashboard_content_security_policy"] = dashboard_content_security_policy
    self._pending_security_config = SecurityConfig(**kwargs)
    return self
```

### Step 4: Tests in `tests/test_integration/test_security_headers.py`

Follow the CORS test pattern at `tests/test_integration/test_cors.py`. Test classes:

```python
"""Tests for security headers middleware integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.config import SecurityConfig
from agent_gateway.gateway import Gateway

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE_WORKSPACE = FIXTURES_DIR / "workspace"


def _make_gateway(**overrides: object) -> Gateway:
    gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
    return gw


@pytest.fixture
async def client() -> AsyncClient:
    """Client with default security headers (enabled by default)."""
    gw = _make_gateway()
    async with gw:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
```

**Test classes to implement:**

1. **`TestSecurityHeadersDefault`** -- Verify all 5 headers are present on `/v1/health` with default values.
2. **`TestSecurityHeadersCustom`** -- Use `use_security_headers(x_frame_options="SAMEORIGIN")`, verify the override.
3. **`TestSecurityHeadersDisabled`** -- Set `security.enabled: false` via config, verify no security headers present.
4. **`TestSecurityHeadersDashboardCsp`** -- Verify dashboard paths get the relaxed CSP while API paths get the strict CSP. (Requires dashboard to be enabled; alternatively, test the middleware class directly.)
5. **`TestUseSecurityHeadersApi`** -- Fluent API tests:
   - `use_security_headers()` returns `self`
   - `use_security_headers()` after start raises `RuntimeError`
   - Config values are stored correctly in `_pending_security_config`
6. **`TestSecurityHeadersOnErrorResponses`** -- Verify headers appear on 404 responses (not just 200s).

**Specific assertions to make:**

```python
# Default headers check
assert resp.headers["x-content-type-options"] == "nosniff"
assert resp.headers["x-frame-options"] == "DENY"
assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
assert resp.headers["content-security-policy"] == "default-src 'self'"
assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
```

### Step 5: Update `examples/test-project/workspace/gateway.yaml`

Add after the `rate_limit` section:

```yaml
security:
  enabled: true
  # x_frame_options: DENY
  # strict_transport_security: "max-age=31536000; includeSubDomains"
  # content_security_policy: "default-src 'self'"
```

### Step 6: Update `examples/test-project/app.py`

Add a comment after the CORS/rate-limit section (around line 101, after the dashboard block) showing customization is possible:

```python
# --- Security headers ---
# Enabled by default. Customize if needed:
# gw.use_security_headers(x_frame_options="SAMEORIGIN")
```

Since security headers are enabled by default, no explicit call is needed. The comment demonstrates the override pattern.

### Step 7: Create `docs/guides/security-headers.md`

Follow the structure of `docs/guides/cors.md`:

1. Introduction paragraph explaining what security headers protect against
2. **Configuration via `gateway.yaml`** -- full YAML example with table of fields
3. **Fluent API** -- `use_security_headers()` example
4. **Default behavior** -- note that headers are enabled by default (unlike CORS/rate-limit)
5. **Dashboard CSP** -- explain that dashboard paths automatically get a relaxed CSP
6. **Disabling** -- show `security.enabled: false` for when a reverse proxy handles headers
7. **Common Patterns** section:
   - Production behind Nginx (disable HSTS in gateway, let Nginx handle it)
   - Embedding in iframes (change X-Frame-Options to SAMEORIGIN)

### Step 8: Update `docs/guides/configuration.md`

Add a `### security` section after the rate_limit section, following the same format:

```yaml
security:
  enabled: true                          # Enabled by default (set false to disable)
  x_content_type_options: "nosniff"
  x_frame_options: "DENY"
  strict_transport_security: "max-age=31536000; includeSubDomains"
  content_security_policy: "default-src 'self'"
  referrer_policy: "strict-origin-when-cross-origin"
```

### Step 9: Update `docs/api-reference/configuration.md`

Add a `## SecurityConfig` section after `RateLimitConfig`, with a table of all fields, types, and defaults.

### Step 10: Update `docs/api-reference/gateway.md`

Add a `#### use_security_headers` section after `use_rate_limit`, following the same format:

```python
def use_security_headers(
    *,
    x_content_type_options: str = "nosniff",
    x_frame_options: str = "DENY",
    strict_transport_security: str = "max-age=31536000; includeSubDomains",
    content_security_policy: str = "default-src 'self'",
    referrer_policy: str = "strict-origin-when-cross-origin",
    dashboard_content_security_policy: str | None = None,
) -> Gateway
```

### Step 11: Update `docs/llms.txt`

Add security headers to the feature list and configuration section.

### Step 12: Update `mkdocs.yml`

Add under Guides nav, after "Rate Limiting":

```yaml
- Security Headers: guides/security-headers.md
```

## Acceptance Criteria

- [ ] All 5 security headers present on every HTTP response by default (no configuration needed)
- [ ] Dashboard paths get relaxed CSP; API paths get strict CSP
- [ ] Configurable via `gateway.yaml` (`security:` section)
- [ ] Configurable via fluent API (`gw.use_security_headers(...)`)
- [ ] Opt-out via `security.enabled: false`
- [ ] Fluent API overrides YAML config (same precedence as CORS)
- [ ] `use_security_headers()` after startup raises `RuntimeError`
- [ ] Headers present on error responses (401, 404, 429), not just 200s
- [ ] No new dependencies (pure ASGI, no third-party packages)
- [ ] All tests pass: `uv run pytest -m "not e2e" -x -q`
- [ ] Type checks pass: `uv run mypy src/`
- [ ] Lint passes: `uv run ruff check src/ tests/`
- [ ] Example project updated
- [ ] Documentation updated (guide, configuration, API reference, llms.txt)

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| CSP breaks dashboard UI | Use a relaxed dashboard-specific CSP with `'unsafe-inline'` for scripts/styles. Test dashboard manually via `make dev`. |
| HSTS causes issues in development (non-TLS) | Set `strict_transport_security: ""` to disable. Document this in the guide. |
| Headers conflict with reverse proxy headers | Document that when behind Nginx/Caddy with its own security headers, users should disable the gateway's (`security.enabled: false`). Duplicate headers are generally safe (browser uses the first). |
| Middleware ordering wrong | Security headers middleware wraps outermost (added first in `_do_startup`, before CORS/rate-limit/auth) so headers appear on all responses including error responses from inner middleware. |

## Verification Checklist

```bash
uv run ruff format src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -m "not e2e" -x -q
```

Then manually verify with `make dev`:
```bash
curl -I http://localhost:8000/v1/health
# Confirm all 5 security headers in response
```

## References

- **Pattern template (CORS):** `src/agent_gateway/config.py` lines 271-287, `src/agent_gateway/gateway.py` lines 607-624, 1168-1198
- **ASGI middleware template:** `src/agent_gateway/auth/middleware.py`
- **Test template:** `tests/test_integration/test_cors.py`
- **Docs template:** `docs/guides/cors.md`
- **Spec:** `docs/plans/publish/10-security-headers.md`
