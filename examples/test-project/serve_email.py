"""Lightweight server for testing RAG context — needs only smtp4dev.

Start smtp4dev first:
    docker compose up -d smtp4dev

Then run:
    uv run python examples/test-project/serve_email.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(os.path.dirname(__file__))

from agent_gateway import ContextRetriever, Gateway


class EmailHistoryRetriever:
    """Example retriever that returns relevant email thread context."""

    THREADS: dict[str, list[str]] = {
        "onboarding": [
            "Thread with Marcus (Feb 18): Discussed webhook delivery guarantees. "
            "Marcus needs SLA numbers by Friday.",
            "Thread with Priya (Feb 19): Confirmed API rate limits are 1000 req/min. "
            "Will share updated docs tomorrow.",
        ],
        "project": [
            "Thread with Sarah (Feb 17): Q1 planning session scheduled for Thursday. "
            "Need to finalize budget numbers.",
            "Thread with Team (Feb 18): Design mockups approved. Moving to "
            "engineering sprint next week.",
        ],
    }

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        results: list[str] = []
        query_lower = query.lower()
        for topic, threads in self.THREADS.items():
            if topic in query_lower or any(
                word in query_lower for word in topic.split()
            ):
                results.extend(threads)
        if not results:
            for threads in self.THREADS.values():
                results.extend(threads[:1])
        return results

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass


gw = Gateway(workspace="./workspace", title="RAG Context Demo", auth=False)

# Register the retriever (referenced as "email-history" in AGENT.md)
gw.use_retriever("email-history", EmailHistoryRetriever())


# Stub tools that the other agents need (so workspace loads cleanly)
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
