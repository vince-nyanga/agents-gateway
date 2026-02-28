"""Test project for agent-gateway development."""

import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel
from retrievers import EmailHistoryRetriever
from starlette.staticfiles import StaticFiles

from agent_gateway import Gateway
from agent_gateway.engine.models import ExecutionOptions

load_dotenv()

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "agent-gateway")
KEYCLOAK_ISSUER = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"

# Use Keycloak OAuth2 for API auth when KEYCLOAK_API=1 is set
use_keycloak_api = os.environ.get("KEYCLOAK_API", "").strip() in ("1", "true")

gw_kwargs: dict = {
    "workspace": "./workspace",
    "title": "Acme AI Hub",
    "description": "Acme Corp's intelligent automation platform powered by agent-gateway.",
    "version": "0.1.0",
    # Caller-supplied tags are merged with gateway defaults (de-duplicated by name).
    # Gateway defaults (Health, Agents, Chat, etc.) are always included automatically.
    "openapi_tags": [
        {"name": "Demo", "description": "Example endpoints for testing gateway features."},
    ],
}

# When API is protected with OAuth2, configure Swagger UI to show the login button
if use_keycloak_api:
    gw_kwargs["swagger_ui_init_oauth"] = {
        "clientId": os.environ.get("KEYCLOAK_API_CLIENT_ID", "agw-api"),
        "clientSecret": os.environ.get("KEYCLOAK_API_CLIENT_SECRET", "agw-api-secret"),
        "scopes": "openid",
    }
    gw_kwargs["swagger_ui_oauth2_redirect_url"] = "/docs/oauth2-redirect"

gw = Gateway(**gw_kwargs)

# Mount static files for branding assets (icon, favicon, etc.)
gw.mount("/static", StaticFiles(directory="static"), name="static")

# --- Pluggable backends (fluent API) ---
# Distributed scheduler locking: enabled in gateway.yaml (scheduler.distributed_lock)
# Auto-detects backend from configured Redis queue or Postgres persistence.
# Prevents duplicate fires when running multiple gateway instances.

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

# API auth: Keycloak OAuth2 or static API key
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

# Memory: auto-selects SQL backend (per-user) when Postgres is configured,
# otherwise falls back to file-based (MEMORY.md per agent).
# To force file-based: gw.use_file_memory()

# --- Dashboard ---
# Supports password auth (default) or OAuth2/OIDC SSO (mutually exclusive).
# Set KEYCLOAK_DASHBOARD=1 to use Keycloak SSO for the dashboard.
# Otherwise falls back to username/password.

use_keycloak_dashboard = os.environ.get("KEYCLOAK_DASHBOARD", "").strip() in ("1", "true")

if use_keycloak_dashboard:
    # Admin credentials enable a fallback username/password login alongside SSO,
    # useful for break-glass access when the OAuth2 provider is unavailable.
    gw.use_dashboard(
        title="Acme AI Hub",
        subtitle="Intelligent Automation Platform",
        logo_url="/static/logo.png",
        favicon_url="/static/icon.png",
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
    # Dashboard role-based access:
    #   Admin user (admin/adminpass):
    #     - Full access to all pages: Agents, Executions, Analytics, Conversations, Schedules
    #     - Conversations page shows ALL conversations including those with no user_id
    #   Regular user (user/userpass):
    #     - Can access: Agents, Conversations, Notifications, Chat
    #     - Cannot access: Executions, Analytics, Schedules (redirected to Agents page)
    #     - Conversations page shows only their own conversations
    gw.use_dashboard(
        title="Acme AI Hub",
        subtitle="Intelligent Automation Platform",
        logo_url="/static/logo.png",
        favicon_url="/static/icon.png",
        auth_username="user",
        auth_password=os.environ.get("DASHBOARD_PASSWORD", "userpass"),
        admin_username="admin",
        admin_password=os.environ.get("DASHBOARD_ADMIN_PASSWORD", "adminpass"),
        primary_color="#2563eb",
        sidebar_color="#0f172a",
    )

# Admin Dashboard Management (requires login as admin):
# 1. Agents page: click agent name -> detail/edit page (admin only)
# 2. Edit description, model, tags -> saves to AGENT.md and reloads
# 3. Disable/enable agent toggle -> disabled agents return 422 on invoke
# 4. Schedules page: click edit icon -> schedule detail/edit page (admin only)
# 5. Edit cron expression, message, timezone -> updates APScheduler live

# --- Security headers ---
# Enabled by default. Customize if needed:
# gw.use_security_headers(x_frame_options="SAMEORIGIN")

# --- Notifications (optional — configure via env vars) ---
# Delivery tracking is automatic when persistence + notifications are configured.
# View delivery status at GET /v1/notifications or in the dashboard Notifications page.

slack_token = os.environ.get("SLACK_BOT_TOKEN")
if slack_token:
    gw.use_slack_notifications(
        bot_token=slack_token,
        default_channel=os.environ.get("SLACK_DEFAULT_CHANNEL", "#agent-alerts"),
    )

webhook_url = os.environ.get("WEBHOOK_URL")
if webhook_url:
    gw.use_webhook_notifications(
        url=webhook_url,
        name="default",
        secret=os.environ.get("WEBHOOK_SECRET", ""),
    )

# --- MCP servers ---
# Register an MCP server via the fluent API (stdio transport).
# The server is started as a subprocess and tools are auto-discovered.
gw.add_mcp_server(
    name="test-tools",
    transport="stdio",
    command="python",
    args=["mcp_test_server.py"],
)

# --- BigQuery MCP server (stdio transport) ---
# Requires: pip install mcp-server-bigquery
# Set BIGQUERY_PROJECT to your GCP project ID to enable.
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

# --- MCP server with encrypted headers (streamable_http) ---
# Set MCP_HTTP_SERVER_URL to enable. Headers are encrypted at rest.
mcp_http_url = os.environ.get("MCP_HTTP_SERVER_URL")
if mcp_http_url:
    gw.add_mcp_server(
        "http-with-headers",
        "streamable_http",
        url=mcp_http_url,
        headers={
            "Authorization": os.environ.get("MCP_HTTP_AUTH_HEADER", "Bearer changeme"),
            "X-API-Version": "2024-01-01",
        },
    )

# --- MCP server with OAuth2 client_credentials auth ---
# Set MCP_OAUTH2_TOKEN_URL, MCP_OAUTH2_CLIENT_ID, MCP_OAUTH2_CLIENT_SECRET,
# and MCP_OAUTH2_SERVER_URL to enable.
mcp_oauth2_url = os.environ.get("MCP_OAUTH2_SERVER_URL")
if mcp_oauth2_url:
    gw.add_mcp_server(
        "oauth2-mcp",
        "streamable_http",
        url=mcp_oauth2_url,
        credentials={
            "auth_type": "oauth2_client_credentials",
            "token_url": os.environ["MCP_OAUTH2_TOKEN_URL"],
            "client_id": os.environ["MCP_OAUTH2_CLIENT_ID"],
            "client_secret": os.environ["MCP_OAUTH2_CLIENT_SECRET"],
            "scopes": os.environ.get("MCP_OAUTH2_SCOPES", "").split(","),
        },
    )

# --- MCP server with Google service account auth ---
# Set GCP_SA_KEY_JSON (raw JSON string) and GCP_MCP_SERVER_URL to enable.
# Requires: pip install agent-gateway[gcp]
gcp_mcp_url = os.environ.get("GCP_MCP_SERVER_URL")
if gcp_mcp_url:
    import json as _json

    gw.add_mcp_server(
        "gcp-mcp",
        "streamable_http",
        url=gcp_mcp_url,
        credentials={
            "auth_type": "google_service_account",
            "service_account_json": _json.loads(os.environ["GCP_SA_KEY_JSON"]),
            "scopes": os.environ.get(
                "GCP_MCP_SCOPES",
                "https://www.googleapis.com/auth/bigquery",
            ).split(","),
        },
    )

# --- MCP server with custom token provider ---
# Example showing how to plug in a custom McpTokenProvider for any auth scheme.
# Uncomment and adapt for your use case:
#
# from agent_gateway.mcp.auth import McpTokenProvider
#
# class MyCustomProvider:
#     server_name = "custom-mcp"
#     async def get_token(self) -> str:
#         return "my-custom-token"
#
# gw.add_mcp_server(
#     "custom-mcp",
#     "streamable_http",
#     url="https://my-mcp-server.example.com/mcp",
#     token_provider=MyCustomProvider(),
# )

# --- Context retrievers ---

gw.use_retriever("email-history", EmailHistoryRetriever())

# --- Chart tools ---


_chart_store: dict[str, bytes] = {}


def _fig_to_url(fig: "Figure") -> str:
    """Render a matplotlib figure to PNG bytes, store in memory, return a URL path."""
    import uuid
    from io import BytesIO

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    png_bytes = buf.read()
    buf.close()
    chart_id = uuid.uuid4().hex[:12]
    _chart_store[chart_id] = png_bytes
    return f"/api/charts/{chart_id}.png"


@gw.get("/api/charts/{chart_id}.png", tags=["Demo"])
async def serve_chart(chart_id: str):
    """Serve a generated chart image from memory."""
    from starlette.responses import Response

    png = _chart_store.get(chart_id)
    if png is None:
        return Response(status_code=404, content="Chart not found")
    return Response(content=png, media_type="image/png")


@gw.tool(name="bar-chart")
async def bar_chart(
    title: str,
    labels: list[str],
    values: list[float],
    xlabel: str = "",
    ylabel: str = "",
) -> dict:
    """Generate a bar chart. Use for comparing categories (e.g., top names, counts)."""
    import ast
    import json

    def _parse(val: object) -> object:
        if not isinstance(val, str):
            return val
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return ast.literal_eval(val)

    labels = _parse(labels)  # type: ignore[assignment]
    values = _parse(values)  # type: ignore[assignment]

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="whitegrid", palette="muted")
    fig, ax = plt.subplots(figsize=(10, 6))
    palette = sns.color_palette("muted", len(labels))
    bars = ax.bar(range(len(labels)), values, color=palette)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title(title, fontsize=14, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{val:,.0f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    plt.tight_layout()
    uri = _fig_to_url(fig)
    plt.close(fig)
    return f"![{title}]({uri})"


@gw.tool(name="line-chart")
async def line_chart(
    title: str,
    x_values: list[str],
    y_series: dict[str, list[float]],
    xlabel: str = "",
    ylabel: str = "",
) -> dict:
    """Generate a line chart with one or more series. Use for trends over time."""
    import ast
    import json

    # LLMs sometimes pass JSON strings (or Python-style dicts with single quotes)
    def _parse(val: object) -> object:
        if not isinstance(val, str):
            return val
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return ast.literal_eval(val)

    x_values = _parse(x_values)  # type: ignore[assignment]
    y_series = _parse(y_series)  # type: ignore[assignment]

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="whitegrid", palette="muted")
    fig, ax = plt.subplots(figsize=(10, 6))
    palette = sns.color_palette("muted", len(y_series))
    for i, (name, values) in enumerate(y_series.items()):
        ax.plot(
            x_values[: len(values)], values,
            marker="o", label=name, color=palette[i], linewidth=2,
        )
    ax.set_title(title, fontsize=14, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    if len(y_series) > 1:
        ax.legend()
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    uri = _fig_to_url(fig)
    plt.close(fig)
    return f"![{title}]({uri})"


@gw.tool(name="pie-chart")
async def pie_chart(
    title: str,
    labels: list[str],
    values: list[float],
) -> dict:
    """Generate a pie chart. Use for showing proportions or market share."""
    import ast
    import json

    def _parse(val: object) -> object:
        if not isinstance(val, str):
            return val
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return ast.literal_eval(val)

    labels = _parse(labels)  # type: ignore[assignment]
    values = _parse(values)  # type: ignore[assignment]

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="whitegrid")
    fig, ax = plt.subplots(figsize=(8, 8))
    palette = sns.color_palette("muted", len(labels))
    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        colors=palette,
        startangle=90,
    )
    for text in autotexts:
        text.set_fontsize(9)
    ax.set_title(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    uri = _fig_to_url(fig)
    plt.close(fig)
    return f"![{title}]({uri})"


# --- Code tools ---


@gw.tool()
async def echo(message: str) -> dict:
    """Echo a message back - for testing the tool pipeline."""
    return {"echo": message}


@gw.tool()
async def add_numbers(a: float, b: float) -> dict:
    """Add two numbers - for testing structured params."""
    return {"result": a + b}


@gw.tool(
    name="process-data",
    description="Simulate a long-running data processing task. Returns a summary after processing.",  # noqa: E501
)
async def process_data(query: str, duration_seconds: float = 5.0) -> dict:
    """Simulate a long-running data processing task."""
    duration_seconds = min(max(duration_seconds, 1.0), 30.0)  # clamp 1-30s
    await asyncio.sleep(duration_seconds)
    return {
        "query": query,
        "processing_time_seconds": duration_seconds,
        "records_processed": 1_247,
        "summary": f"Processed data for query '{query}' in {duration_seconds}s. "
        "Found 1,247 matching records across 3 data sources.",
    }


class WeatherService:
    """Example: registering a class method as a tool."""

    BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

    def __init__(self, api_key: str | None = None, units: str = "metric"):
        self.api_key = api_key or os.environ.get("WEATHER_API_KEY", "")
        self.units = units

    async def get_weather(self, destination: str, date: str) -> dict:
        """Get the weather forecast for a destination on a given date."""
        if not self.api_key:
            return {"error": "OPENWEATHER_API_KEY not set", "destination": destination}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self.BASE_URL,
                params={"q": destination, "appid": self.api_key, "units": self.units},
            )
            if resp.status_code != 200:
                return {
                    "error": f"OpenWeather API error: {resp.status_code}",
                    "destination": destination,
                    "date": date,
                }
            data = resp.json()
            weather = data.get("weather", [{}])[0]
            main = data.get("main", {})
            wind = data.get("wind", {})
            return {
                "destination": destination,
                "date": date,
                "condition": weather.get("description", "unknown"),
                "temperature_celsius": main.get("temp"),
                "humidity_percent": main.get("humidity"),
                "wind_kmh": round((wind.get("speed", 0)) * 3.6, 1),
            }


weather = WeatherService()
gw.tool(name="get-weather")(weather.get_weather)


@gw.tool(
    name="search-flights",
    description="Search for available flights between two cities on a given date.",
)
async def search_flights(origin: str, destination: str, date: str) -> dict:
    """Return mock flight results."""
    return {
        "origin": origin,
        "destination": destination,
        "date": date,
        "flights": [
            {"airline": "SkyWay", "departure": "08:00", "arrival": "11:30", "price_usd": 320},
            {"airline": "AeroConnect", "departure": "14:15", "arrival": "17:45", "price_usd": 275},
            {"airline": "GlobalJet", "departure": "19:00", "arrival": "22:30", "price_usd": 410},
        ],
    }


# --- Pydantic output schemas ---
# Define structured output models and use them with ExecutionOptions.
# The gateway converts the model to JSON Schema for the LLM prompt and
# returns a validated Pydantic instance in result.output.


class TravelPlan(BaseModel):
    destination: str
    summary: str
    flights: list[dict]
    hotels: list[dict]
    total_estimated_cost_usd: float


class MathResult(BaseModel):
    answer: float
    explanation: str


# --- Lifecycle hooks ---


@gw.on("agent.invoke.before")
async def log_invoke(agent_id, message, execution_id, **kw):
    print(f"[hook] invoke start: agent={agent_id} exec={execution_id}")


@gw.on("agent.invoke.after")
async def log_result(agent_id, execution_id, result, **kw):
    stop = result.stop_reason.value
    print(f"[hook] invoke done: agent={agent_id} exec={execution_id} stop={stop}")


@gw.on("tool.execute.before")
async def log_tool(tool_name, agent_id, **kw):
    print(f"[hook] tool start: {tool_name} (agent={agent_id})")


@gw.on("tool.execute.after")
async def log_tool_done(tool_name, duration_ms, success, **kw):
    print(f"[hook] tool done: {tool_name} {duration_ms}ms ok={success}")


@gw.get("/api/health")
async def health():
    return {"status": "ok", "project": "test-project"}


# --- Programmatic usage examples ---
# These functions show how to use the gateway from Python code.
# They're wired up as custom routes below.


@gw.get("/api/demo/structured-output")
async def demo_structured_output():
    """Invoke the assistant with a Pydantic output schema."""
    result = await gw.invoke(
        "assistant",
        "What is 12 * 15? Explain your reasoning.",
        options=ExecutionOptions(output_schema=MathResult),
    )
    if isinstance(result.output, MathResult):
        return {"answer": result.output.answer, "explanation": result.output.explanation}
    return {"raw_text": result.raw_text, "validation_errors": result.validation_errors}


@gw.get("/api/demo/travel-plan")
async def demo_travel_plan():
    """Invoke the travel planner with a Pydantic output schema."""
    result = await gw.invoke(
        "travel-planner",
        "Plan a 3-day trip to Tokyo from San Francisco, departing 2025-04-01.",
        options=ExecutionOptions(output_schema=TravelPlan),
    )
    if isinstance(result.output, TravelPlan):
        return {
            "destination": result.output.destination,
            "summary": result.output.summary,
            "flights": result.output.flights,
            "hotels": result.output.hotels,
            "total_estimated_cost_usd": result.output.total_estimated_cost_usd,
        }
    return {"raw_text": result.raw_text, "validation_errors": result.validation_errors}


@gw.get("/api/demo/send-email")
async def demo_send_email():
    """Invoke the email drafter with RAG context (static + retriever)."""
    result = await gw.invoke(
        "email-drafter",
        "Send a follow-up email to sarah@example.com about the onboarding project. "
        "Remind her about the webhook SLA numbers we need by Friday.",
    )
    return {"output": result.raw_text, "stop_reason": result.stop_reason.value}


@gw.get("/api/demo/conversation-cost")
async def demo_conversation_cost():
    """Demonstrate conversation tracing — multi-turn chat with cost tracking."""
    # Turn 1
    session_id, result1 = await gw.chat(
        "assistant",
        "What is the capital of France?",
    )

    # Turn 2 — same session
    _, result2 = await gw.chat(
        "assistant",
        "And what about Germany?",
        session_id=session_id,
    )

    cost1 = result1.usage.cost_usd if result1.usage else 0
    cost2 = result2.usage.cost_usd if result2.usage else 0
    return {
        "session_id": session_id,
        "turns": 2,
        "total_cost_usd": round(cost1 + cost2, 6),
        "turn_1": result1.raw_text[:200],
        "turn_2": result2.raw_text[:200],
    }


@gw.get("/api/demo/notification-deliveries")
async def demo_notification_deliveries():
    """Query recent notification delivery records to verify tracking."""
    records = await gw._notification_repo.list_recent(limit=10)
    total = await gw._notification_repo.count()
    failed = await gw._notification_repo.count(status="failed")
    return {
        "total_deliveries": total,
        "failed_deliveries": failed,
        "recent": [
            {
                "id": r.id,
                "agent_id": r.agent_id,
                "channel": r.channel,
                "status": r.status,
                "attempts": r.attempts,
            }
            for r in records
        ],
    }


if __name__ == "__main__":
    gw.run(port=8000)
