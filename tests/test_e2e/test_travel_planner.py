"""E2E tests for the travel-planner agent (multi-tool invocation)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


async def test_invoke_travel_planner(client: AsyncClient) -> None:
    """Invoke travel-planner and verify multiple tools are called."""
    resp = await client.post(
        "/v1/agents/travel-planner/invoke",
        json={
            "message": "Plan the trip. Use all available tools.",
            "input": {
                "destination": "Paris",
                "origin": "London",
                "departure_date": "2025-07-15",
                "nights": 3,
            },
        },
        timeout=60,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["agent_id"] == "travel-planner"
    # The agent should call at least 3 of the 4 travel tools
    assert data["usage"]["tool_calls"] >= 3


async def test_travel_planner_details(client: AsyncClient) -> None:
    """GET /v1/agents/travel-planner returns agent with 4 travel tools."""
    resp = await client.get("/v1/agents/travel-planner")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "travel-planner"
    expected_tools = {"get-weather", "search-flights", "search-hotels", "search-activities"}
    assert expected_tools.issubset(set(data.get("tools", [])))
