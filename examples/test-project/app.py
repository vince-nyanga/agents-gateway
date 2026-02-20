"""Test project for agent-gateway development."""

import asyncio
import os

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel
from retrievers import EmailHistoryRetriever

from agent_gateway import Gateway
from agent_gateway.engine.models import ExecutionOptions

load_dotenv()

gw = Gateway(
    workspace="./workspace",
    title="Test Project",
)

# --- Pluggable backends (fluent API) ---

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
gw.use_api_keys(
    [
        {
            "name": "dev",
            "key": os.environ.get("AGENT_GATEWAY_API_KEY", "dev-api-key-change-me"),
            "scopes": ["*"],
        }
    ]
)
gw.use_file_memory()

# --- Notifications (optional — configure via env vars) ---

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

# --- Context retrievers ---

gw.use_retriever("email-history", EmailHistoryRetriever())

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
    description="Simulate a long-running data processing task. Returns a summary after processing.",
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


if __name__ == "__main__":
    gw.run(port=8000)
