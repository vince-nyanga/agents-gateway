"""Integration test: full end-to-end agent invocation flow."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from agent_gateway.engine.models import ToolCall
from agent_gateway.gateway import Gateway

from .conftest import make_llm_response, make_test_client


async def test_invoke_agent_full_flow(gateway_app: Gateway, mock_llm_completion: Any) -> None:
    """POST /v1/agents/test-agent/invoke -> tool call -> text response."""
    responses = [
        make_llm_response(
            tool_calls=[ToolCall(name="echo", arguments={"message": "hello"}, call_id="call_1")]
        ),
        make_llm_response(text="The echo tool returned: hello"),
    ]
    ac = await make_test_client(gateway_app)
    try:
        with mock_llm_completion(responses):
            resp = await ac.post(
                "/v1/agents/test-agent/invoke",
                json={"message": "Say hello"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "test-agent"
        assert data["status"] == "completed"
        assert data["result"]["raw_text"] == "The echo tool returned: hello"
        assert data["execution_id"]
        assert data["usage"]["llm_calls"] == 2
        assert data["usage"]["tool_calls"] == 1
    finally:
        await ac.aclose()
        await gateway_app._shutdown()


async def test_invoke_agent_simple_text(gateway_app: Gateway, mock_llm_completion: Any) -> None:
    """POST /v1/agents/test-agent/invoke -> direct text response (no tools)."""
    responses = [make_llm_response(text="Hello! I'm a test agent.")]
    ac = await make_test_client(gateway_app)
    try:
        with mock_llm_completion(responses):
            resp = await ac.post(
                "/v1/agents/test-agent/invoke",
                json={"message": "Hi there"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"]["raw_text"] == "Hello! I'm a test agent."
    finally:
        await ac.aclose()
        await gateway_app._shutdown()


async def test_health_endpoint(client: AsyncClient) -> None:
    """GET /v1/health returns gateway status."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agent_count"] >= 1


async def test_list_agents(client: AsyncClient) -> None:
    """GET /v1/agents lists discovered agents."""
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    agent_ids = [a["id"] for a in data]
    assert "test-agent" in agent_ids


async def test_get_agent(client: AsyncClient) -> None:
    """GET /v1/agents/{id} returns agent details."""
    resp = await client.get("/v1/agents/test-agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "test-agent"


async def test_list_tools(client: AsyncClient) -> None:
    """GET /v1/tools lists all tools including code-based."""
    resp = await client.get("/v1/tools")
    assert resp.status_code == 200
    data = resp.json()
    tool_names = [t["name"] for t in data]
    assert "echo" in tool_names
    assert "add-numbers" in tool_names


async def test_get_tool(client: AsyncClient) -> None:
    """GET /v1/tools/{id} returns tool details."""
    resp = await client.get("/v1/tools/echo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "echo"
    assert data["source"] == "code"


async def test_execution_id_header(gateway_app: Gateway, mock_llm_completion: Any) -> None:
    """Response includes X-Execution-Id header."""
    responses = [make_llm_response(text="done")]
    ac = await make_test_client(gateway_app)
    try:
        with mock_llm_completion(responses):
            resp = await ac.post(
                "/v1/agents/test-agent/invoke",
                json={"message": "test"},
            )

        assert "x-execution-id" in resp.headers
        assert resp.headers["x-execution-id"]
    finally:
        await ac.aclose()
        await gateway_app._shutdown()


async def test_list_skills(client: AsyncClient) -> None:
    """GET /v1/skills lists discovered skills."""
    resp = await client.get("/v1/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
