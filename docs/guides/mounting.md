# Sub-Application Mounting

Mount a Gateway instance into an existing FastAPI application, giving you full feature parity -- including the dashboard, auth, OAuth2, static assets, and all background subsystems.

## When to Use

- You have an existing FastAPI app and want to add AI agent capabilities
- You want the gateway API and dashboard served under a path prefix (e.g. `/ai/`)
- You need multiple services in a single process

## Basic Usage

```python
from fastapi import FastAPI
from agent_gateway import Gateway

app = FastAPI(title="My Application")

gw = Gateway(workspace="./workspace")
gw.mount_to(app, path="/ai")
```

All gateway routes are now available under `/ai/`:

- **API**: `/ai/v1/health`, `/ai/v1/agents`, `/ai/v1/invoke/{agent_id}`, ...
- **Dashboard**: `/ai/dashboard/`
- **OpenAPI docs**: `/ai/docs`

## Full Example with Dashboard

```python
from fastapi import FastAPI
from agent_gateway import Gateway

app = FastAPI(title="My Application")

@app.get("/")
async def root():
    return {"message": "Main application"}

gw = Gateway(workspace="./workspace")

gw.use_dashboard(
    title="AI Hub",
    auth_username="user",
    auth_password="secret",
    admin_username="admin",
    admin_password="adminpass",
)

gw.mount_to(app, path="/ai")
```

Run with:

```bash
uvicorn app:app --reload
```

Visit `http://localhost:8000/ai/dashboard/` for the dashboard.

## How It Works

### Lifespan Wiring

`mount_to()` wraps the parent app's lifespan to include gateway startup and shutdown. The gateway's background tasks (scheduler, workers, MCP connections) all start and stop with the parent app.

### Path Prefix Handling

Starlette sets `scope["root_path"]` to the mount prefix but does **not** modify `scope["path"]`. Route handlers see stripped paths (e.g. `/v1/agents`), but ASGI middleware sees the full un-stripped path (e.g. `/ai/v1/agents`). The gateway's auth and security-header middleware both strip `root_path` from the path before matching, so authentication and CSP rules apply correctly when mounted.

URLs sent to the **browser** (links, redirects, form actions, static asset URLs) must include the full prefix. The gateway handles this automatically:

- **Templates**: A `base_path` Jinja2 global is injected into all templates
- **Python redirects**: All `RedirectResponse` URLs include the prefix
- **JavaScript**: The chat streaming endpoint reads the base path from a `<meta>` tag

### Features Supported When Mounted

All features work identically:

- Dashboard with login, OAuth2/SSO, admin pages
- Static assets (CSS, JS, images)
- HTMX endpoints
- API authentication (API keys, JWT)
- Scheduling and background execution
- MCP server connections
- Notifications
- Chat streaming

## API Reference

### `Gateway.mount_to(parent, path="/gateway")`

Mount this gateway as a sub-application.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `parent` | `FastAPI` | required | The parent FastAPI application |
| `path` | `str` | `"/gateway"` | Mount path prefix (must not be empty or `/`) |

**Returns:** The parent `FastAPI` app (for chaining).

**Raises:** `ConfigError` if the gateway has already started or if `path` is empty or `"/"`.

## Configuration

No changes to `gateway.yaml` are needed when mounting. All configuration (auth, persistence, scheduling, etc.) works the same. The only difference is that API and dashboard URLs include the mount prefix.

!!! note
    The `server.host` and `server.port` settings in `gateway.yaml` are ignored when mounted — the parent app controls the HTTP server.

## Running the Example

The example project includes a mounted configuration at `examples/test-project/app_mounted.py`:

```bash
cd examples/test-project
uvicorn app_mounted:app --reload --port 8000
```

- Main app: `http://localhost:8000/`
- Gateway API: `http://localhost:8000/ai/v1/health`
- Dashboard: `http://localhost:8000/ai/dashboard/`

## Standalone vs Mounted

When running standalone (no `mount_to`), the gateway behaves exactly as before. The `base_path` template variable is an empty string, so all paths resolve to their original values. No configuration changes are needed.

## Troubleshooting

**Dashboard login redirects to wrong URL**: This should not happen -- all redirects are prefix-aware. If it does, ensure you are accessing the dashboard at `{prefix}/dashboard/` (with trailing slash).

**Static assets return 404**: Static file serving is handled by the gateway sub-app. Verify the mount path matches what you passed to `mount_to()`.

**Lifespan events not firing**: `mount_to()` wraps the parent app's lifespan. If the parent app has its own lifespan, both will run. If you are using a test client, ensure it triggers lifespan events (e.g., `async with AsyncClient(app=app, ...)`).

**Branding URLs include the mount prefix**: If you serve custom branding assets (e.g. `logo_url`, `favicon_url`) from the parent app's static files, the URLs must include the full path as seen by the browser. For example, if the parent app serves `/static/logo.png`, use that path directly. If the gateway serves the assets, prefix them: `logo_url="/ai/static/logo.png"`.

**Cannot mount at root (`/`)**: By design, `mount_to()` requires a non-empty path prefix. To run the gateway at the root, use it as the main app directly instead of mounting.

## Running Behind an HTTPS Reverse Proxy

In production, the gateway (and its parent FastAPI app) is typically deployed behind a TLS-terminating proxy: Cloud Run, Fly.io, Nginx, ALB, Cloudflare, Caddy, and so on. The proxy talks to Uvicorn over plain HTTP, so by default:

- `scope['scheme']` is `http`, not the external `https`.
- `request.url_for()` returns an internal URL — OAuth2 `redirect_uri` breaks.
- The dashboard session cookie is **not** marked `Secure`, and strict browsers / intermediaries drop it.
- Chat streaming can fall into a silent-spinner state if the session is dropped (the client `fetch()` follows the 302 to the login page and tries to parse HTML as SSE).

### Quick checklist

1. **Tell Uvicorn to trust forwarded headers** (preferred):

    ```bash
    uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ```

    If you cannot set Uvicorn flags (e.g. running under Gunicorn with a Uvicorn worker), use the fluent method instead:

    ```python
    gw.use_proxy_headers(forwarded_allow_ips="*")
    ```

    !!! danger "Only enable when a trusted proxy sits in front of the app"
        Without a trusted upstream, any client can inject `X-Forwarded-Host` and hijack the OAuth2 `redirect_uri` — an open-redirect / account-takeover vector. Narrow `forwarded_allow_ips` to your known proxy peers wherever possible.

2. **Mark the session cookie `Secure`** — leave `session_cookie_https_only=None` (the default) so it auto-resolves to `True` whenever `trust_forwarded` is on, or pass `True` explicitly:

    ```python
    gw.use_dashboard(
        ...,
        session_cookie_https_only=None,   # auto: True when trust_forwarded
        session_cookie_same_site="lax",
    )
    ```

3. **Register the OAuth2 `redirect_uri` with your IdP as the EXTERNAL URL.** For a gateway mounted at `/ai` on `app.example.com`, register exactly:

    ```
    https://app.example.com/ai/dashboard/oauth2/callback
    ```

    On every authorize start the gateway logs the computed callback URL at INFO (`OAuth2 redirect_uri=...`). Grep your logs if the IdP rejects the authorize request.

### Forwarded headers consumed

| Header | Effect |
|---|---|
| `X-Forwarded-Proto` | Sets `scope['scheme']` (→ `request.url.scheme`, `request.url_for()`) |
| `X-Forwarded-For` | Sets `scope['client']` |
| `X-Forwarded-Host` | Used by `_build_callback_url()` (and Uvicorn's middleware) to rewrite the OAuth2 redirect URI |

### Middleware ordering

When `use_proxy_headers()` is called, the gateway installs `ProxyHeadersMiddleware` **outside** `SessionMiddleware`. That guarantees `scope['scheme']` is corrected **before** session cookie evaluation, so the `Secure` attribute check resolves against the real external scheme.

### Dashboard chat under HTTPS

The dashboard's streaming chat (`POST /dashboard/chat/stream`) uses `fetch(..., { redirect: 'error' })` and verifies the response `Content-Type` starts with `text/event-stream`. If either check fails (e.g. the session expired and the server tried to 302 to `/dashboard/login`), the client navigates to the login page immediately rather than silently spinning. Nothing is required on the operator side for this; it's pure client-side hardening.

### Troubleshooting

**Login succeeds but the browser bounces back to `/dashboard/login`**: the session cookie is being dropped. Confirm the response to `POST /dashboard/login` sets a cookie with `Secure`, and that `trust_forwarded` is on (or you passed `session_cookie_https_only=True`).

**OAuth2 IdP rejects the authorize request**: the registered `redirect_uri` must match what the gateway computes. Look for `OAuth2 redirect_uri=...` in the gateway logs and paste that exact URL into the IdP's allowed redirect URIs list.

**Chat shows a spinner that never resolves**: this was the pre-fix symptom. Upgrade the gateway, re-load the dashboard (hard refresh to pick up the new `app.js`), and verify DevTools → Network shows `Accept: text/event-stream` and `redirect: error` on `/dashboard/chat/stream`.
