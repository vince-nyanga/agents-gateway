"""E2E tests for error handling (no LLM calls needed)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


async def test_invoke_unknown_agent_404(client: AsyncClient) -> None:
    """POST /v1/agents/nonexistent/invoke returns 404."""
    resp = await client.post(
        "/v1/agents/nonexistent/invoke",
        json={"message": "hello"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "agent_not_found"


async def test_invoke_empty_body_422(client: AsyncClient) -> None:
    """POST /v1/agents/assistant/invoke with no message field returns 422."""
    resp = await client.post(
        "/v1/agents/assistant/invoke",
        json={},
    )
    assert resp.status_code == 422


async def test_chat_bad_session_404(client: AsyncClient) -> None:
    """POST /v1/agents/assistant/chat with invalid session_id returns 404."""
    resp = await client.post(
        "/v1/agents/assistant/chat",
        json={"message": "Hi", "session_id": "sess_does_not_exist"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "session_not_found"


async def test_get_unknown_agent_404(client: AsyncClient) -> None:
    """GET /v1/agents/nonexistent returns 404."""
    resp = await client.get("/v1/agents/nonexistent")
    assert resp.status_code == 404


async def test_get_unknown_tool_404(client: AsyncClient) -> None:
    """GET /v1/tools/nonexistent returns 404."""
    resp = await client.get("/v1/tools/nonexistent")
    assert resp.status_code == 404


async def test_get_unknown_skill_404(client: AsyncClient) -> None:
    """GET /v1/skills/nonexistent returns 404."""
    resp = await client.get("/v1/skills/nonexistent")
    assert resp.status_code == 404
