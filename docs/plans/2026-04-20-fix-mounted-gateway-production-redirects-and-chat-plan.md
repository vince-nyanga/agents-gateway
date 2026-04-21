---
title: "fix: Redirects and chat streaming break when Gateway is mounted behind an HTTPS proxy"
type: fix
status: implemented (F1 F2 F3 F5 F6; F4 deferred)
date: 2026-04-20
---

# fix: Redirects and chat streaming break when Gateway is mounted behind an HTTPS proxy

## Revision history

- **v2 (2026-04-20)**: Rewritten after plan review rejected v1. Scope tightened to strict HTTPS-proxy regressions. Corrected the chat-hang root cause (it is `fetch()` auto-following the auth redirect, not a 302 raised mid-stream). Removed the invalid `SessionMiddleware(path=...)` kwarg. Dropped F4 (runtime `base_path`) entirely — the existing sub-app mounting plan already sets `env.globals["base_path"]` at mount time and that is sufficient for every bug reported by the user. F4 is deferred for a future `uvicorn --root-path` support plan.

## Dependency on the sub-app mounting plan

This plan builds on partially-landed work from `docs/plans/2026-02-28-feat-sub-app-mounting-plan.md` (status: active). The following pieces are already live in the tree and are **prerequisites**, not work-items for this plan:

- `Gateway._mount_prefix: str` attribute (`gateway.py:184`)
- `Gateway.mount_to(parent, path)` method (`gateway.py:302-359`)
- `make_get_dashboard_user(auth_config, mount_prefix=...)` (`dashboard/auth.py`)
- `make_require_admin(auth_config, mount_prefix=...)` (`dashboard/auth.py`)
- `make_login_handler(auth_config, mount_prefix=...)` (`dashboard/auth.py:89-122`) — already issues `RedirectResponse(url=f"{mount_prefix}/dashboard/", status_code=303)`
- `env.globals["base_path"] = mount_prefix` in `_build_templates()` (`dashboard/router.py`)
- `<meta name="base-path" content="{{ base_path }}">` in `base.html` / `login.html`
- `getBasePath()` in `static/dashboard/app.js` reading the meta tag
- All template `href/action/hx-*` attributes already prefixed with `{{ base_path }}`

If any of the above are not yet merged when this plan starts implementation, **pause and wait** — do not implement both plans in parallel. They touch overlapping files (`gateway.py` middleware install, `dashboard/oauth2.py`, `dashboard/router.py`, and templates).

## Scope decision (explicit)

This plan is **strictly scoped to the HTTPS-proxy-behind-a-reverse-proxy regressions** reported by the user. Concretely:

- **In scope**: F1 session cookie flags surface, F2 ProxyHeadersMiddleware install, F3 OAuth2 `redirect_uri` external-URL construction, F5 chat-stream auth-failure hardening (client + server), F6 SSE response header cleanup.
- **Out of scope (deferred)**: Runtime-aware `base_path` resolution via `request.scope["root_path"]` (formerly F4). The mount-time `base_path` that the sub-app plan already ships is sufficient for the reported bugs. A separate plan will introduce runtime `root_path` support to unlock `uvicorn --root-path=…` deployments and parent apps that themselves mount the gateway inside a deeper path.
- **Out of scope (deferred)**: Session-cookie `Path` scoping to the mount prefix. Starlette's `SessionMiddleware` has no `path` kwarg (v1 plan was wrong about this) and a `/`-scoped cookie works functionally. A custom `SessionMiddleware` subclass is overkill for this plan.

## Overview

When a `Gateway` is mounted into a parent FastAPI app via `gw.mount_to(app, path="/gateway")` and that parent app is deployed behind an HTTPS reverse proxy (Cloud Run, Fly.io, Nginx, ALB, Cloudflare) that terminates TLS and talks to the app over HTTP, two user-visible regressions occur:

1. **Login produces no redirect** — submitting the login form returns 303 but the browser ends up back on the login page.
2. **Chat hangs indefinitely** — after sending a message, the loading indicator spins forever; no tokens arrive.

Both work fine on `http://localhost:…` — the failure surface is specifically **HTTPS + proxy + session cookies + server-generated URLs**.

## Problem Statement / Root Cause Analysis

### Background facts (established by inspection)

- `src/agent_gateway/gateway.py:2071-2088` — `SessionMiddleware` installed with `https_only=False` and `same_site="lax"` **hard-coded** (both the `middleware_stack` wrap branch and the `add_middleware` branch).
- `src/agent_gateway/dashboard/auth.py` — `make_get_dashboard_user` is a FastAPI dependency; when no session, it raises `HTTPException(status_code=302, headers={"Location": f"{mount_prefix}/dashboard/login"})` or `204` + `HX-Redirect` for HTMX.
- `src/agent_gateway/dashboard/oauth2.py:83, 138` — OAuth2 uses `request.url_for("oauth2_callback")` to build the `redirect_uri` sent to the IdP.
- `src/agent_gateway/dashboard/static/dashboard/app.js:122` — Chat submission: `await fetch(getBasePath() + '/dashboard/chat/stream', { method: 'POST', body: formData })`. **No `redirect` option passed**, so it defaults to `"follow"`. No `Accept` header set.
- `src/agent_gateway/dashboard/router.py` — the chat stream handler declares `current_user: DashboardUser = Depends(get_dashboard_user)` as a function-signature dependency.

### Root cause (a): Login appears to "not redirect"

On an HTTPS deployment where the proxy terminates TLS and talks to Uvicorn over plain HTTP:

1. Uvicorn sees `scope['scheme'] == 'http'` (no `ProxyHeadersMiddleware` installed by default).
2. `SessionMiddleware` is configured with `https_only=False` → the `Secure` attribute is NOT set on `Set-Cookie`. Browsers accept the cookie at `Set-Cookie` time.
3. Some intermediaries (Cloudflare Access, Zscaler, browsers in "HTTPS-only" mode, strict corporate proxies) will **drop non-`Secure` cookies on HTTPS origins**. In that case the cookie never lands. The 303 redirect is followed; the dashboard handler sees no session and redirects back to `/dashboard/login`. User appears stuck.
4. Even when the cookie *does* land: if the operator is using OAuth2, `request.url_for("oauth2_callback")` returns `http://<internal-host>/...` because the scheme in the ASGI scope is wrong. The IdP either rejects the authorize request (registered `redirect_uri` is `https://…`) or sends the browser to an `http://` URL the proxy refuses. Login appears broken.

**The primary fixes are F1 (surface `https_only` so operators can turn on `Secure`) and F2 (install `ProxyHeadersMiddleware` so `scope['scheme']` is correct) + F3 (belt-and-braces forwarded-header fallback for OAuth2 callback URL).**

### Root cause (b): Chat hangs indefinitely

The v1 plan claimed `get_dashboard_user` raises `HTTPException(302)` "inside a `StreamingResponse`" and Starlette cannot send the status. **This is wrong.** `get_dashboard_user` is declared as a FastAPI dependency at the function signature:

```python
async def chat_stream(
    request: Request,
    current_user: DashboardUser = Depends(get_dashboard_user),
    ...
) -> StreamingResponse:
```

Dependencies resolve **before** the handler body runs. When the dependency raises 302, FastAPI translates it into a plain `RedirectResponse` and returns it cleanly at connection time — the `StreamingResponse` is never constructed.

The actual hang mechanism is entirely client-side:

1. The dashboard chat JS calls `fetch(url, { method: 'POST', body: formData })` with **no `redirect` option**, which defaults to `"follow"`.
2. Session cookie is missing or was dropped (root cause (a)).
3. Server: dependency raises `HTTPException(302, Location="/dashboard/login")`.
4. Browser's `fetch` silently follows the 302 to the login page.
5. Login page returns `200 OK` with `Content-Type: text/html`.
6. `response.ok` is `true`. Client proceeds to `response.body.getReader()`, passes the HTML bytes through `parseSSEEvents`, which finds no `event: token` frames.
7. The loading indicator (`chat-loading`) is only hidden inside the `event.type === 'token'` branch. No tokens → indicator never hides → "hangs forever."

**The primary fix is F1 (stop the cookie from being dropped) and F3 (fix OAuth2 redirect if that was the login path). F5 is hardening**: change the JS to set `redirect: "error"` (or `redirect: "manual"`) AND verify the response `Content-Type` starts with `text/event-stream`; if not, treat it as an auth-loss and navigate to the login page. Optionally, have the server emit an explicit `event: error\ndata: {"redirect": "…"}` frame for inline auth-loss mid-stream so the JS can drive navigation.

### Summary of fixes

| # | Change | Why |
|---|---|---|
| F1 | Surface session cookie flags (`https_only`, `same_site`, `session_cookie` name, `domain`, `max_age`) through `DashboardAuthConfig` so operators can mark cookies `Secure` on HTTPS deployments. | So cookies are not dropped by strict browsers / intermediaries on HTTPS. |
| F2 | Install Uvicorn `ProxyHeadersMiddleware` when a new `ProxyConfig.trust_forwarded` flag is true. Document the Uvicorn CLI equivalent. | So `scope['scheme']` / `request.url_for()` reflect the external URL. |
| F3 | In OAuth2 `authorize`/`callback`, use a helper `_build_callback_url(request)` that prefers `request.url_for()` then falls back to `X-Forwarded-Proto`/`X-Forwarded-Host` rewriting. Guard the non-standard-port edge case. | Works even when `--proxy-headers` was forgotten. |
| F5 | Chat JS: pass `redirect: "error"`, check response `Content-Type` starts with `text/event-stream`; on mismatch or redirect error, navigate to `{base_path}/dashboard/login`. Server: have `chat_stream` emit `event: error` + `redirect` when auth fails inline. | Makes auth-loss a loud, fast failure instead of a silent spinner. |
| F6 | Remove misleading `Connection: keep-alive` from SSE response; add `Cache-Control: no-cache, no-transform`; keep `X-Accel-Buffering: no`. | Cloud proxies don't buffer HTTP/2 SSE responses. |

## Technical Approach

### Design Decisions

1. **Do not auto-enable `Secure` unconditionally** — developers run locally on `http://localhost:8000` and need logins to work. `DashboardAuthConfig.session_cookie_https_only` defaults to `None` meaning "follow `ProxyConfig.trust_forwarded`: if the operator has enabled proxy-forwarded headers, they are almost certainly behind HTTPS → `Secure=True`; else `Secure=False`." This is the *least surprising* auto-default.

2. **Do not invent a forwarded-header parser** — use Uvicorn's shipped `ProxyHeadersMiddleware`. Gate it behind `ProxyConfig.trust_forwarded` with a `forwarded_allow_ips` narrowing field (precedent: `RateLimitConfig.trust_forwarded_for`). Document the Uvicorn CLI flag equivalent (`--proxy-headers --forwarded-allow-ips=*`) as the recommended production setup; our middleware install is a fallback for operators who can't set Uvicorn flags (e.g. running under Gunicorn with a Uvicorn worker).

3. **Config surface follows the rest of the codebase** — `ProxyConfig` is a `pydantic` model on `GatewayConfig`; add a **`gw.use_proxy_headers(...)` fluent method** matching the precedent of `use_rate_limit()` / `use_security_headers()` / `use_cors()`. Do not add a `Gateway(proxy=…)` constructor kwarg — that pattern is not used elsewhere.

4. **JS fetch hardening** — `redirect: "error"` causes the `fetch` Promise to reject when the server sends a redirect; combined with a `Content-Type` check this gives the client two independent tripwires. Use `redirect: "error"` rather than `"manual"`: `"manual"` returns an opaque-redirect response which we'd then have to distinguish by status 0, whereas `"error"` throws — simpler. Also set `Accept: text/event-stream` explicitly so a future proxy misconfiguration is more likely to fail loudly.

5. **Middleware ordering** — `ProxyHeadersMiddleware` must wrap OUTSIDE `SessionMiddleware` so that `scope['scheme']` and `scope['server']` are corrected BEFORE session cookie evaluation. In Starlette/FastAPI, the LAST `add_middleware()` call wraps the OUTERMOST layer of the ASGI chain (so it runs FIRST per request). Therefore: install `SessionMiddleware` first (inner), then `ProxyHeadersMiddleware` second (outer). The same ordering discipline applies to the `middleware_stack` wrap branch — `ProxyHeadersMiddleware` must wrap the stack AFTER `SessionMiddleware` has wrapped it.

6. **No runtime `base_path`** — deferred. The sub-app plan already sets `env.globals["base_path"]` at mount time; this is sufficient for mounted deployments. When the user later asks for `uvicorn --root-path` support, a follow-up plan can introduce a `Jinja2Templates` subclass that reads `request.scope["root_path"]` at render time. Do not monkey-patch `templates.TemplateResponse` (mypy strict will reject it).

## Implementation Steps

### Phase 1: Configuration surface

**Files modified:**
- `src/agent_gateway/config.py`
- `src/agent_gateway/gateway.py` (add `use_proxy_headers` fluent method)

**Tasks:**

1. Extend `DashboardAuthConfig`:
   ```python
   class DashboardAuthConfig(BaseModel):
       # ...existing fields...
       session_cookie_name: str = "agw_dashboard_session"
       session_cookie_same_site: Literal["lax", "strict", "none"] = "lax"
       session_cookie_https_only: bool | None = None  # None = auto
       session_cookie_domain: str | None = None
       session_max_age_seconds: int = 86400
   ```
   Defaults MUST preserve existing behavior: `session_cookie_name` defaults to `"agw_dashboard_session"` (current hard-coded value); `session_max_age_seconds` defaults to `86400` (current value); `session_cookie_https_only=None` resolves to `False` when `trust_forwarded=False` (matching current behavior).

2. Add `ProxyConfig`:
   ```python
   class ProxyConfig(BaseModel):
       """Trust forwarded headers from an upstream reverse proxy."""
       trust_forwarded: bool = False
       forwarded_allow_ips: str = "127.0.0.1"
   ```
   Wire into `GatewayConfig` alongside `cors`, `rate_limit`, `security_headers`, etc.

3. Add `Gateway.use_proxy_headers()` fluent method:
   ```python
   def use_proxy_headers(
       self,
       *,
       trust_forwarded: bool = True,
       forwarded_allow_ips: str = "127.0.0.1",
   ) -> Gateway:
       """Trust X-Forwarded-* headers from an upstream proxy.

       Example::

           gw.use_proxy_headers(forwarded_allow_ips="*")
       """
       if self._started:
           raise RuntimeError("Cannot configure proxy headers after gateway has started")
       self._pending_proxy_config = ProxyConfig(
           trust_forwarded=trust_forwarded,
           forwarded_allow_ips=forwarded_allow_ips,
       )
       return self
   ```
   Store in `_pending_proxy_config` consistent with the pending-registration pattern; apply during `_startup()` by setting `self._config.proxy = ...`.

**Success criteria:**
- `tests/test_config.py` covers new fields and defaults.
- `mypy src/` passes.

### Phase 2: SessionMiddleware wiring (flag-driven)

**Files modified:**
- `src/agent_gateway/gateway.py` (around lines 2067-2093)

**Tasks:**

1. Resolve `https_only`:
   ```python
   https_only_cfg = dash_config.auth.session_cookie_https_only
   if https_only_cfg is None:
       # auto: match trust_forwarded (operator behind a proxy → HTTPS)
       https_only = self._config.proxy.trust_forwarded
   else:
       https_only = https_only_cfg
   ```

2. Replace BOTH branches (direct `middleware_stack` wrap AND `add_middleware`) with config-driven flags. **Do not pass `path=...`** — `SessionMiddleware` has no such kwarg.
   ```python
   session_kwargs = dict(
       secret_key=session_secret,
       session_cookie=dash_config.auth.session_cookie_name,
       max_age=dash_config.auth.session_max_age_seconds,
       https_only=https_only,
       same_site=dash_config.auth.session_cookie_same_site,
   )
   if dash_config.auth.session_cookie_domain:
       session_kwargs["domain"] = dash_config.auth.session_cookie_domain

   if self.middleware_stack is not None:
       self.middleware_stack = SessionMiddleware(app=self.middleware_stack, **session_kwargs)
   else:
       self.add_middleware(SessionMiddleware, **session_kwargs)
   ```

**Success criteria:**
- Explicit `session_cookie_https_only=True` → `Set-Cookie` has `Secure`.
- Default `session_cookie_https_only=None` + `trust_forwarded=True` → `Set-Cookie` has `Secure`.
- Default `session_cookie_https_only=None` + `trust_forwarded=False` → no `Secure` (local-dev default preserved).
- Cookie continues to work in all existing dashboard tests.

### Phase 3: ProxyHeadersMiddleware install

**Files modified:**
- `src/agent_gateway/gateway.py` (alongside the session middleware block in `_maybe_init_dashboard`, and in the top-level middleware install region)

**Tasks:**

1. After SessionMiddleware is installed (so that ProxyHeaders wraps OUTSIDE it and runs FIRST per request), install `ProxyHeadersMiddleware` when `self._config.proxy.trust_forwarded` is true:
   ```python
   if self._config.proxy.trust_forwarded:
       from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

       trusted = self._config.proxy.forwarded_allow_ips
       if self.middleware_stack is not None:
           self.middleware_stack = ProxyHeadersMiddleware(
               self.middleware_stack, trusted_hosts=trusted
           )
       else:
           self.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted)
   ```
   Apply this to BOTH branches (the `middleware_stack is not None` wrap path AND the `add_middleware` path). Both must produce the same layering: `ProxyHeaders` outside `Session`.

2. Note on `uvicorn>=0.34`: verify the import path. If Uvicorn renames or moves it in a future release, we'll pin the min version in `pyproject.toml`. Current: `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware`.

3. Document the Uvicorn CLI flag equivalent in `docs/guides/mounting.md` and recommend it as the preferred production setup; the middleware install is for operators who can't set Uvicorn flags.

**Success criteria:**
- With `trust_forwarded=True` and request header `X-Forwarded-Proto: https`, a test route asserts `request.url.scheme == "https"`.
- Without the flag, the header is ignored.
- A dedicated middleware-ordering test constructs the app, walks `self.user_middleware` (or the actual middleware stack), and asserts `ProxyHeadersMiddleware` is LAYERED OUTSIDE `SessionMiddleware`. The test must check the `middleware_stack is not None` branch too (exercise by calling a request first to build the stack, then inspecting `self.middleware_stack`).

### Phase 4: OAuth2 external callback URL

**Files modified:**
- `src/agent_gateway/dashboard/oauth2.py`

**Tasks:**

1. Add a module-private helper:
   ```python
   def _build_callback_url(request: Request) -> str:
       """External-facing absolute URL for the oauth2_callback route.

       Strategy: start with request.url_for() (correct when ProxyHeadersMiddleware
       is installed). If forwarded headers are present AND the resolved URL's
       scheme/host don't match them, rewrite — belt-and-braces for setups where
       the operator forgot --proxy-headers.
       """
       url = str(request.url_for("oauth2_callback"))
       fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
       fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
       if not (fwd_proto and fwd_host):
           return url

       from urllib.parse import urlparse, urlunparse
       parsed = urlparse(url)

       # fwd_host may already contain a port (e.g. "app.example.com:8443").
       # Use it as-is — do NOT try to preserve parsed.port, the forwarded header
       # is authoritative for the external port seen by the browser.
       netloc = fwd_host
       return urlunparse(parsed._replace(scheme=fwd_proto, netloc=netloc))
   ```
   Document the non-standard-port behavior in the docstring: `X-Forwarded-Host` may include an explicit port and that wins over whatever `url_for()` resolved.

2. Replace both call sites (`oauth2.py:83, 138`) that currently call `request.url_for("oauth2_callback")` with `_build_callback_url(request)`.

3. Log the computed callback URL at INFO level exactly once per OAuth2 flow start so operators can diagnose IdP `redirect_uri` mismatches: `logger.info("OAuth2 redirect_uri=%s", callback_url)`. Do not log on every callback hit — only on `authorize`.

**Success criteria:**
- Test: with `trust_forwarded=True` + `X-Forwarded-Proto: https, X-Forwarded-Host: app.example.com`, mounted at `/gw`, the 303 to the IdP contains `redirect_uri=https%3A%2F%2Fapp.example.com%2Fgw%2Fdashboard%2Foauth2%2Fcallback`.
- Test: with `X-Forwarded-Host: app.example.com:8443` (non-standard port), the `redirect_uri` contains `https://app.example.com:8443/...`.
- Test: without forwarded headers, `_build_callback_url` returns `request.url_for()` unchanged.

### Phase 5: Chat stream — auth-failure hardening

**Files modified:**
- `src/agent_gateway/dashboard/static/dashboard/app.js` (chat submit)
- `src/agent_gateway/dashboard/router.py` (chat stream handler)

#### 5a. Client-side hardening (primary fix for the hang symptom)

In `app.js`, update the `sendChatMessage` fetch call:

```javascript
const loginUrl = getBasePath() + '/dashboard/login';

let response;
try {
  response = await fetch(getBasePath() + '/dashboard/chat/stream', {
    method: 'POST',
    body: formData,
    redirect: 'error',                         // reject on any redirect
    headers: { 'Accept': 'text/event-stream' },
  });
} catch (err) {
  // redirect: 'error' rejects with TypeError on redirect — treat as auth loss
  window.location.assign(loginUrl);
  return;
}

if (!response.ok) {
  bubbleContent.textContent = 'Error: ' + response.statusText;
  bubble.classList.add('message-error');
  return;
}

const ctype = (response.headers.get('content-type') || '').toLowerCase();
if (!ctype.startsWith('text/event-stream')) {
  // Server returned HTML (likely a login page) — navigate to login
  window.location.assign(loginUrl);
  return;
}
```

Rationale: two independent tripwires — `redirect: 'error'` catches the `fetch`-follows-302 case; the `Content-Type` check catches any pathway that returns a 200 HTML page (e.g. a proxy-injected login page). Either one reaching the client ends in a fast, explicit navigation to `/dashboard/login` rather than a silent spinner.

#### 5b. Server-side hardening (inline auth-loss during stream)

Today the dashboard `chat_stream` declares `current_user: DashboardUser = Depends(get_dashboard_user)` at the signature. This works fine: the 302 is returned at connection time, before the stream begins — it just isn't visible to the JS fetch because of `redirect: "follow"`. After 5a, the client will navigate to login on any redirect, so this alone resolves the reported symptom.

OPTIONAL hardening — if the product wants the server to emit a structured SSE error for mid-stream session loss (e.g. session expires while a long generation is running): remove the `Depends()` at the signature, call `get_dashboard_user(request)` inside the `event_generator`, catch `HTTPException`, and yield:

```python
yield 'event: error\n'
yield f'data: {json.dumps({"message": "Session expired", "redirect": _url("/dashboard/login")})}\n\n'
return
```

Then extend the JS `event.type === 'error'` branch to honor `redirect`:

```javascript
} else if (event.type === 'error') {
  if (event.data.redirect) {
    window.location.assign(event.data.redirect);
    return;
  }
  // ...existing setup_url / message handling...
}
```

**Decision**: implement 5a unconditionally (it is the primary fix). Implement 5b only if mid-stream expiry is a realistic concern for the product (session lifetime is 24h by default — rare). Mark 5b as a follow-up in the PR description; gated on user feedback.

**Success criteria:**
- With no session cookie, POST to `/dashboard/chat/stream` from the dashboard UI results in the browser navigating to `/dashboard/login` within one round-trip. No spinner hang.
- With a valid session, normal token streaming works unchanged.
- Jest/browser-level integration (manual verification via `make dev` + Network panel): confirm `redirect: 'error'` is in the request options.

### Phase 6: SSE response header cleanup

**Files modified:**
- `src/agent_gateway/dashboard/router.py` (chat_stream `StreamingResponse`)

**Tasks:**

1. Update the headers dict:
   ```python
   return StreamingResponse(
       event_generator(),
       media_type="text/event-stream",
       headers={
           "Cache-Control": "no-cache, no-transform",
           "X-Accel-Buffering": "no",
           # Intentionally no "Connection: keep-alive" — not meaningful under HTTP/2.
       },
   )
   ```

**Success criteria:**
- Response headers match the new set in tests.
- Manual verification: Cloudflare / GCP LB do not buffer under a TLS termination proxy.

### Phase 7: Middleware path-prefix sanity check

**Files modified:** none (verification only).

**Tasks:**

1. Confirm by test that `src/agent_gateway/api/middleware/security.py` and `src/agent_gateway/auth/middleware.py` already strip `scope.get("root_path", "")` before path-based decisions. This code is already in place (sub-app mounting plan). Add a single regression test that mounts the gateway at `/gw`, sets `X-Forwarded-Proto: https`, hits a dashboard route, and asserts the security headers / auth allowlisting still apply.

## Testing Strategy

**New test files:**
- `tests/dashboard/test_session_cookie_flags.py`
- `tests/dashboard/test_proxy_headers.py`
- `tests/dashboard/test_oauth2_redirect_uri_forwarded.py`
- `tests/dashboard/test_chat_stream_sse_headers.py`
- `tests/dashboard/test_middleware_ordering.py`

**Unit / integration tests:**

1. **Session cookie flags** (`test_session_cookie_flags.py`):
   - `session_cookie_https_only=True` → `Set-Cookie` has `Secure`.
   - `session_cookie_https_only=False` → no `Secure`.
   - `session_cookie_https_only=None` + `trust_forwarded=True` → `Secure`.
   - `session_cookie_https_only=None` + `trust_forwarded=False` → no `Secure`.
   - Custom `session_cookie_name="foo"` → cookie name is `foo`.
   - Custom `session_cookie_domain="example.com"` → `Domain=example.com`.

2. **Proxy headers** (`test_proxy_headers.py`):
   - With `use_proxy_headers(trust_forwarded=True, forwarded_allow_ips="*")` and `X-Forwarded-Proto: https`, a test route reading `request.url.scheme` sees `https`.
   - Without the flag, the header is ignored.
   - `trusted_hosts="127.0.0.1"` rejects forwarded headers from an untrusted peer.

3. **OAuth2 redirect_uri** (`test_oauth2_redirect_uri_forwarded.py`):
   - Mounted at `/gw` + `X-Forwarded-Proto: https, X-Forwarded-Host: app.example.com` → authorize 303 contains `redirect_uri=https%3A%2F%2Fapp.example.com%2Fgw%2Fdashboard%2Foauth2%2Fcallback`.
   - With `X-Forwarded-Host: app.example.com:8443` → contains `:8443`.
   - Without forwarded headers → uses `request.url_for()` unchanged.
   - Belt-and-braces: `trust_forwarded=False` but forwarded headers present → helper STILL rewrites (safety net, documented).

4. **SSE headers** (`test_chat_stream_sse_headers.py`):
   - Response has `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`, no `Connection:`.

5. **Middleware ordering** (`test_middleware_ordering.py`):
   - Inspect `self.user_middleware` after `_maybe_init_dashboard` completes; assert `ProxyHeadersMiddleware` appears AFTER `SessionMiddleware` in the `user_middleware` list (the LAST-added wraps outermost). Exercise BOTH the `add_middleware` path and the `middleware_stack is not None` wrap path — trigger the latter by making a request first so the stack is built.

6. **Chat stream client-side hardening** (browser-level): no Python test. Manual verification with `make dev` + `run_mounted.sh` — document expected behavior in the PR description.

**Example project integration:**
- Run `examples/test-project/scripts/run_mounted.sh`, log in as `admin`, confirm redirect lands on `/gateway/dashboard/`, confirm chat streams.
- Repeat behind a local TLS proxy (`caddy reverse-proxy --from https://localhost.test --to http://localhost:8000`) with `use_proxy_headers(forwarded_allow_ips="*")`.

## Example Project Updates

**File**: `examples/test-project/app_mounted.py` (update the existing file from the sub-app plan)

Add the proxy-headers hook:
```python
gw.use_proxy_headers(forwarded_allow_ips="*")
gw.use_dashboard(
    ...,
    session_cookie_https_only=None,   # auto: True when trust_forwarded
    session_cookie_same_site="lax",
)
gw.mount_to(app, path="/ai")
```

**File**: `examples/test-project/scripts/run_mounted.sh` (new)

```bash
#!/usr/bin/env bash
# Run the mounted example with Uvicorn proxy-headers enabled.
uv run uvicorn app_mounted:app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips='*'
```

## Documentation Updates

1. **`docs/guides/mounting.md`** (existing, updated by the sub-app plan) — Add a "Running behind an HTTPS reverse proxy" section:
   - When you need `ProxyConfig` / `use_proxy_headers()`.
   - Table of `X-Forwarded-*` headers consumed.
   - Explicit Uvicorn CLI example and why it's preferred.
   - Required OAuth2 provider setting: registered `redirect_uri` MUST be the EXTERNAL HTTPS URL (`https://app.example.com/gw/dashboard/oauth2/callback`).
   - Session cookie checklist: for HTTPS-only deployments, set `session_cookie_https_only=True` (or leave `None` and enable `trust_forwarded`).

2. **`docs/guides/dashboard.md`** — Document the new `DashboardAuthConfig` fields.

3. **`docs/guides/configuration.md`** + **`docs/api-reference/configuration.md`** — Document `ProxyConfig` and new `DashboardAuthConfig` fields.

4. **`docs/guides/authentication.md`** — Troubleshooting entry: "Login succeeds but I'm redirected back to the login page" → check `session_cookie_https_only` and `trust_forwarded`.

5. **`docs/api-reference/gateway.md`** — Document `Gateway.use_proxy_headers(...)`.

6. **`docs/llms.txt`** — One line: "Behind HTTPS proxy: `gw.use_proxy_headers(forwarded_allow_ips='*')` and launch Uvicorn with `--proxy-headers`."

7. **`docs/changelog.md`** — Next unreleased entry.

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Enabling `trust_forwarded` without a trusted upstream proxy allows header spoofing. | Medium | High | Default `False`; `forwarded_allow_ips` narrows trust; docs warn explicitly. |
| Operator sets `session_cookie_https_only=True` locally and breaks their dev login. | Medium | Low | Doc the auto-default (`None` → follows `trust_forwarded`); example project uses auto. |
| Middleware ordering regression (ProxyHeaders inside Session). | Low | Medium | Dedicated ordering test; run against BOTH branches. |
| `_build_callback_url` rewrites mismatch IdP-registered URI. | Medium | High | INFO log the computed URL at authorize start; docs include exact-match checklist. |
| Uvicorn renames `ProxyHeadersMiddleware` import path in a future release. | Low | Low | Pin min Uvicorn version in `pyproject.toml`. |
| `redirect: "error"` rejects on legitimate 3xx we want to follow (none today). | Low | Low | Chat stream is the only `fetch()` POST in the dashboard; no 3xx expected. |
| Runtime `base_path` not implemented — `uvicorn --root-path` deployments still broken for templates. | Known, accepted | Low | Out of scope; documented; follow-up plan. |

## Verification Checklist

```bash
uv run ruff format src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -m "not e2e" -x -q
```

Manual verification:
- `bash examples/test-project/scripts/run_mounted.sh`, front with `caddy reverse-proxy --from https://localhost.test --to http://localhost:8000`, log in, send a chat — both must work.
- Browser DevTools → Network: confirm `/dashboard/chat/stream` request includes `Accept: text/event-stream` and `redirect: error`.
- Browser DevTools → Application → Cookies: confirm session cookie has `Secure` when behind HTTPS with `trust_forwarded=True`.

## References

- Sub-app mounting plan (prerequisite): `docs/plans/2026-02-28-feat-sub-app-mounting-plan.md`
- Gateway `mount_to`: `src/agent_gateway/gateway.py:302-359`
- SessionMiddleware install site: `src/agent_gateway/gateway.py:2067-2093`
- Dashboard auth dependency: `src/agent_gateway/dashboard/auth.py`
- OAuth2 authorize + callback: `src/agent_gateway/dashboard/oauth2.py:68-256`
- Chat stream handler: `src/agent_gateway/dashboard/router.py:1016-1165`
- Chat stream JS: `src/agent_gateway/dashboard/static/dashboard/app.js:97-188`
- `use_rate_limit` fluent precedent: `src/agent_gateway/gateway.py:1484-1506`
- Rate-limit forwarded-for precedent: `src/agent_gateway/ratelimit.py:27-84`
- Uvicorn ProxyHeadersMiddleware: https://www.uvicorn.org/deployment/#running-behind-nginx
- MDN `fetch` `redirect` option: https://developer.mozilla.org/en-US/docs/Web/API/fetch#redirect
