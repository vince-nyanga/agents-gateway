"""Lightweight server for testing input_schema — no Postgres/RabbitMQ needed."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(os.path.dirname(__file__))

from agent_gateway import Gateway

gw = Gateway(workspace="./workspace", title="Input Schema Demo", auth=False)


@gw.tool(name="get-weather")
async def get_weather(destination: str, date: str) -> dict:
    return {"destination": destination, "condition": "sunny", "temp_c": 22}


@gw.tool(name="search-flights")
async def search_flights(origin: str, destination: str, date: str) -> dict:
    return {"flights": [{"airline": "TestAir", "price_usd": 300}]}


@gw.tool(name="search-hotels")
async def search_hotels(destination: str, checkin: str, nights: int = 3) -> dict:
    return {"hotels": [{"name": "Test Hotel", "price_per_night_usd": 150}]}


@gw.tool(name="search-activities")
async def search_activities(destination: str) -> dict:
    return {"activities": [{"name": "City Tour", "price_usd": 50}]}


@gw.tool(name="echo")
async def echo(message: str) -> dict:
    return {"echo": message}


@gw.tool(name="add-numbers")
async def add_numbers(a: float, b: float) -> dict:
    return {"result": a + b}


if __name__ == "__main__":
    gw.run(port=8000)
