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
