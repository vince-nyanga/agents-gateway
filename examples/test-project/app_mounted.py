"""Example: mounting Agent Gateway into an existing FastAPI app.

Run with: make dev-mounted

- Main app routes at /
- Gateway API at /ai/v1/...
- Gateway dashboard at /ai/dashboard/
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from agent_gateway import Gateway

load_dotenv()

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "agent-gateway")
KEYCLOAK_ISSUER = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"

use_keycloak_api = os.environ.get("KEYCLOAK_API", "").strip() in ("1", "true")

# ── Your existing application ──────────────────────────────────────

app = FastAPI(title="My Application", version="1.0.0")


@app.get("/")
async def root():
    return {"message": "This is the main application", "gateway": "/ai/dashboard/"}


@app.get("/api/status")
async def status():
    return {"status": "ok", "service": "my-app"}


# ── Agent Gateway (mounted as sub-app) ─────────────────────────────

gw_kwargs: dict = {
    "workspace": "./workspace",
    "title": "Acme AI Hub (Mounted)",
    "description": "Gateway mounted inside an existing FastAPI app.",
    "version": "0.1.0",
}

if use_keycloak_api:
    gw_kwargs["swagger_ui_init_oauth"] = {
        "clientId": os.environ.get("KEYCLOAK_API_CLIENT_ID", "agw-api"),
        "clientSecret": os.environ.get("KEYCLOAK_API_CLIENT_SECRET", "agw-api-secret"),
        "scopes": "openid",
    }
    gw_kwargs["swagger_ui_oauth2_redirect_url"] = "/ai/docs/oauth2-redirect"

gw = Gateway(**gw_kwargs)

# Static files for branding
gw.mount("/static", StaticFiles(directory="static"), name="static")

# ── Persistence & Queue ─────────────────────────────────────────────

gw.use_postgres(
    url=os.environ.get(
        "POSTGRES_URL",
        "postgresql+asyncpg://agentgw:agentgw_dev@localhost:54320/agent_gateway",
    ),
)
gw.use_rabbitmq_queue(
    url=os.environ.get(
        "RABBITMQ_URL",
        "amqp://agentgw:agentgw_dev@localhost:56720/",
    ),
)

# ── API Auth ────────────────────────────────────────────────────────

if use_keycloak_api:
    gw.use_oauth2(
        issuer=KEYCLOAK_ISSUER,
        audience=os.environ.get("KEYCLOAK_API_CLIENT_ID", "agw-api"),
    )
else:
    gw.use_api_keys(
        [
            {
                "name": "dev",
                "key": os.environ.get("AGENT_GATEWAY_API_KEY", "dev-api-key-change-me"),
                "scopes": ["*"],
            }
        ]
    )

# ── Dashboard ───────────────────────────────────────────────────────

use_keycloak_dashboard = os.environ.get("KEYCLOAK_DASHBOARD", "").strip() in ("1", "true")

if use_keycloak_dashboard:
    gw.use_dashboard(
        title="Acme AI Hub (Mounted)",
        subtitle="Sub-App Mode",
        logo_url="/ai/static/logo.png",
        favicon_url="/ai/static/icon.png",
        oauth2_issuer=KEYCLOAK_ISSUER,
        oauth2_client_id=os.environ.get("KEYCLOAK_DASHBOARD_CLIENT_ID", "agw-dashboard"),
        oauth2_client_secret=os.environ.get(
            "KEYCLOAK_DASHBOARD_CLIENT_SECRET", "agw-dashboard-secret"
        ),
        primary_color="#2563eb",
        sidebar_color="#0f172a",
        login_button_text="Sign in with Keycloak",
        admin_username="admin",
        admin_password=os.environ.get("DASHBOARD_ADMIN_PASSWORD", "adminpass"),
    )
else:
    gw.use_dashboard(
        title="Acme AI Hub (Mounted)",
        subtitle="Sub-App Mode",
        logo_url="/ai/static/logo.png",
        favicon_url="/ai/static/icon.png",
        auth_username="user",
        auth_password=os.environ.get("DASHBOARD_PASSWORD", "userpass"),
        admin_username="admin",
        admin_password=os.environ.get("DASHBOARD_ADMIN_PASSWORD", "adminpass"),
        primary_color="#2563eb",
        sidebar_color="#0f172a",
    )

# ── MCP Servers ─────────────────────────────────────────────────────

gw.add_mcp_server(
    name="test-tools",
    transport="stdio",
    command="python",
    args=["mcp_test_server.py"],
)

bigquery_project = os.environ.get("BIGQUERY_PROJECT")
if bigquery_project:
    gw.add_mcp_server(
        name="bigquery",
        transport="stdio",
        command="uvx",
        args=[
            "mcp-server-bigquery",
            "--project",
            bigquery_project,
            "--location",
            os.environ.get("BIGQUERY_LOCATION", "us"),
            "--key-file",
            os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS",
                str(Path(__file__).parent / "creds" / "bigquery-sa-key.json"),
            ),
        ],
    )

# ── Mount at /ai ────────────────────────────────────────────────────

gw.mount_to(app, path="/ai")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
