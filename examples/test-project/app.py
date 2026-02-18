"""Test project for agent-gateway development."""

from agent_gateway import Gateway

gw = Gateway(workspace="./workspace", auth=False, title="Test Project")


@gw.tool()
async def echo(message: str) -> dict:
    """Echo a message back - for testing the tool pipeline."""
    return {"echo": message}


@gw.tool()
async def add_numbers(a: float, b: float) -> dict:
    """Add two numbers - for testing structured params."""
    return {"result": a + b}


class WeatherService:
    """Example: registering a class method as a tool."""

    def __init__(self, default_unit: str = "celsius"):
        self.default_unit = default_unit

    async def get_weather(self, destination: str, date: str) -> dict:
        """Get the weather forecast for a destination on a given date."""
        return {
            "destination": destination,
            "date": date,
            "condition": "Sunny",
            "temperature_celsius": 25,
            "humidity_percent": 45,
            "wind_kmh": 12,
            "unit": self.default_unit,
        }


weather = WeatherService(default_unit="celsius")
gw.tool(name="get-weather")(weather.get_weather)


@gw.tool(name="search-flights", description="Search for available flights between two cities on a given date.")
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


# --- Lifecycle hooks ---


@gw.on("agent.invoke.before")
async def log_invoke(agent_id, message, execution_id, **kw):
    print(f"[hook] invoke start: agent={agent_id} exec={execution_id}")


@gw.on("agent.invoke.after")
async def log_result(agent_id, execution_id, result, **kw):
    print(f"[hook] invoke done: agent={agent_id} exec={execution_id} stop={result.stop_reason.value}")


@gw.on("tool.execute.before")
async def log_tool(tool_name, agent_id, **kw):
    print(f"[hook] tool start: {tool_name} (agent={agent_id})")


@gw.on("tool.execute.after")
async def log_tool_done(tool_name, duration_ms, success, **kw):
    print(f"[hook] tool done: {tool_name} {duration_ms}ms ok={success}")


@gw.get("/api/health")
async def health():
    return {"status": "ok", "project": "test-project"}


if __name__ == "__main__":
    gw.run(port=8000)
