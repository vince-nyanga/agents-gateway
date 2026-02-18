"""Test project for agent-gateway development."""

import os

import httpx
from dotenv import load_dotenv

from agent_gateway import Gateway

load_dotenv()

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


if __name__ == "__main__":
    gw.run(port=8000)
