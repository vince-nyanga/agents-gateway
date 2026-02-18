"""Integration test: error handling for API endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from httpx import AsyncClient

from agent_gateway.engine.models import ToolCall
from agent_gateway.gateway import Gateway

from .conftest import make_llm_response, make_test_client


async def test_unknown_agent_404(client: AsyncClient) -> None:
    """POST /v1/agents/nonexistent/invoke -> 404."""
    resp = await client.post(
        "/v1/agents/nonexistent/invoke",
        json={"message": "hello"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "agent_not_found"
    assert "nonexistent" in data["error"]["message"]


async def test_empty_message_422(client: AsyncClient) -> None:
    """POST with missing message field -> 422 validation error."""
    resp = await client.post(
        "/v1/agents/test-agent/invoke",
        json={},
    )
    assert resp.status_code == 422


async def test_invalid_json_422(client: AsyncClient) -> None:
    """POST with invalid JSON -> 422."""
    resp = await client.post(
        "/v1/agents/test-agent/invoke",
        content="not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422


async def test_get_unknown_agent_404(client: AsyncClient) -> None:
    """GET /v1/agents/nonexistent -> 404."""
    resp = await client.get("/v1/agents/nonexistent")
    assert resp.status_code == 404


async def test_get_unknown_skill_404(client: AsyncClient) -> None:
    """GET /v1/skills/nonexistent -> 404."""
    resp = await client.get("/v1/skills/nonexistent")
    assert resp.status_code == 404


async def test_get_unknown_tool_404(client: AsyncClient) -> None:
    """GET /v1/tools/nonexistent -> 404."""
    resp = await client.get("/v1/tools/nonexistent")
    assert resp.status_code == 404


async def test_get_unknown_execution_404(client: AsyncClient) -> None:
    """GET /v1/executions/nonexistent -> 404 (persistence disabled, so always 404)."""
    resp = await client.get("/v1/executions/nonexistent")
    assert resp.status_code == 404


async def test_cancel_unknown_execution_404(client: AsyncClient) -> None:
    """POST /v1/executions/nonexistent/cancel -> 404."""
    resp = await client.post("/v1/executions/nonexistent/cancel")
    assert resp.status_code == 404


async def test_llm_failure_returns_error(gateway_app: Gateway, mock_llm_completion: Any) -> None:
    """LLM exception during execution -> execution completes with error."""

    async def _fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("LLM is down")

    ac = await make_test_client(gateway_app)
    try:
        with patch("agent_gateway.engine.llm.LLMClient.completion", side_effect=_fail):
            resp = await ac.post(
                "/v1/agents/test-agent/invoke",
                json={"message": "test"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error"]
    finally:
        await ac.aclose()
        await gateway_app._shutdown()


async def test_tool_crash_during_execution(gateway_app: Gateway, mock_llm_completion: Any) -> None:
    """Tool crash -> error returned to LLM, loop continues, execution completes."""
    responses = [
        make_llm_response(
            tool_calls=[ToolCall(name="crash-tool", arguments={}, call_id="call_1")]
        ),
        make_llm_response(text="The tool failed, but I recovered."),
    ]

    @gateway_app.tool(name="crash-tool")
    async def crash_tool() -> None:
        """A tool that crashes."""
        raise ValueError("boom!")

    ac = await make_test_client(gateway_app)
    try:
        with mock_llm_completion(responses):
            resp = await ac.post(
                "/v1/agents/test-agent/invoke",
                json={"message": "trigger crash"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "recovered" in data["result"]["raw_text"]
    finally:
        await ac.aclose()
        await gateway_app._shutdown()
