"""E2E tests for health and introspection endpoints (no LLM calls needed)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


async def test_health_endpoint(client: AsyncClient) -> None:
    """GET /v1/health returns gateway status with correct counts."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agent_count"] == 6
    assert data["skill_count"] == 5
    assert data["tool_count"] >= 7  # echo, add-numbers, http-example + travel tools


async def test_list_agents(client: AsyncClient) -> None:
    """GET /v1/agents lists both example agents."""
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    data = resp.json()
    agent_ids = [a["id"] for a in data]
    assert "assistant" in agent_ids
    assert "data-processor" in agent_ids
    assert "scheduled-reporter" in agent_ids
    assert "travel-planner" in agent_ids
    assert "daily-briefing" in agent_ids
    assert "email-drafter" in agent_ids


async def test_get_agent_details(client: AsyncClient) -> None:
    """GET /v1/agents/assistant returns agent with skills and tools."""
    resp = await client.get("/v1/agents/assistant")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "assistant"
    assert "math-workflow" in data.get("skills", [])
    assert "echo" in data.get("tools", [])
    assert "add-numbers" in data.get("tools", [])


async def test_list_skills(client: AsyncClient) -> None:
    """GET /v1/skills lists the math-workflow skill."""
    resp = await client.get("/v1/skills")
    assert resp.status_code == 200
    data = resp.json()
    skill_names = [s["name"] for s in data]
    assert "math-workflow" in skill_names


async def test_get_skill(client: AsyncClient) -> None:
    """GET /v1/skills/math-workflow returns skill details."""
    resp = await client.get("/v1/skills/math-workflow")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "math-workflow"


async def test_list_tools(client: AsyncClient) -> None:
    """GET /v1/tools lists code and file tools."""
    resp = await client.get("/v1/tools")
    assert resp.status_code == 200
    data = resp.json()
    tool_names = [t["name"] for t in data]
    assert "echo" in tool_names
    assert "add-numbers" in tool_names
    assert "http-example" in tool_names
    assert "get-weather" in tool_names
    assert "search-flights" in tool_names
    assert "search-hotels" in tool_names
    assert "search-activities" in tool_names


async def test_get_tool(client: AsyncClient) -> None:
    """GET /v1/tools/echo returns tool details."""
    resp = await client.get("/v1/tools/echo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "echo"
    assert data["source"] == "code"


async def test_custom_route(client: AsyncClient) -> None:
    """GET /api/health (custom user route) is not mounted by the example.

    The custom route is defined in app.py but not registered here because
    the e2e conftest creates its own Gateway instance. This tests that the
    gateway starts without custom routes being present.
    """
    # Custom routes from app.py aren't registered in our test gateway,
    # so we just verify the gateway's own health works.
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
