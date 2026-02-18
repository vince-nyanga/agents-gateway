"""E2E tests for chat endpoint and session management with real LLM calls."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


class TestChatEndpoint:
    """Tests for POST /v1/agents/{agent_id}/chat."""

    async def test_new_session(self, client: AsyncClient) -> None:
        """Chat without session_id creates a new session."""
        resp = await client.post(
            "/v1/agents/assistant/chat",
            json={"message": "Say hello in one sentence."},
            timeout=30,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"].startswith("sess_")
        assert data["agent_id"] == "assistant"
        assert data["status"] == "completed"
        assert data["turn_count"] == 1
        assert data["result"]["raw_text"]

    async def test_multi_turn(self, client: AsyncClient) -> None:
        """Multiple messages with same session_id form a conversation."""
        # Turn 1
        resp1 = await client.post(
            "/v1/agents/assistant/chat",
            json={"message": "My name is TestBot. Remember that."},
            timeout=30,
        )
        assert resp1.status_code == 200
        session_id = resp1.json()["session_id"]
        assert resp1.json()["turn_count"] == 1

        # Turn 2 — reference previous context
        resp2 = await client.post(
            "/v1/agents/assistant/chat",
            json={"message": "What is my name?", "session_id": session_id},
            timeout=30,
        )
        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == session_id
        assert resp2.json()["turn_count"] == 2
        assert "testbot" in resp2.json()["result"]["raw_text"].lower()

    async def test_chat_with_tool_use(self, client: AsyncClient) -> None:
        """Tool calls work within chat context."""
        resp = await client.post(
            "/v1/agents/assistant/chat",
            json={"message": "Use add_numbers to compute 100 + 200."},
            timeout=30,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["usage"]["tool_calls"] >= 1
        assert "300" in data["result"]["raw_text"]

    async def test_chat_streaming(self, client: AsyncClient) -> None:
        """Chat with stream=true returns SSE events."""
        async with client.stream(
            "POST",
            "/v1/agents/assistant/chat",
            json={"message": "Say 'streaming works'", "options": {"stream": True}},
            timeout=30,
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

            events: list[str] = []
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())

        # Should have session, at least one token, and done events
        assert "session" in events
        assert "done" in events


class TestSessionCRUD:
    """Tests for session management endpoints."""

    async def test_list_sessions(self, client: AsyncClient) -> None:
        """GET /v1/sessions lists active sessions after creating one via chat."""
        # Create a session
        resp = await client.post(
            "/v1/agents/assistant/chat",
            json={"message": "Hi"},
            timeout=30,
        )
        session_id = resp.json()["session_id"]

        # List sessions
        resp2 = await client.get("/v1/sessions")
        assert resp2.status_code == 200
        sessions = resp2.json()
        session_ids = [s["session_id"] for s in sessions]
        assert session_id in session_ids

    async def test_get_session(self, client: AsyncClient) -> None:
        """GET /v1/sessions/{id} returns session details."""
        resp = await client.post(
            "/v1/agents/assistant/chat",
            json={"message": "Hello"},
            timeout=30,
        )
        session_id = resp.json()["session_id"]

        resp2 = await client.get(f"/v1/sessions/{session_id}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["session_id"] == session_id
        assert data["agent_id"] == "assistant"
        assert data["turn_count"] == 1

    async def test_delete_session(self, client: AsyncClient) -> None:
        """DELETE /v1/sessions/{id} removes the session."""
        resp = await client.post(
            "/v1/agents/assistant/chat",
            json={"message": "Hi"},
            timeout=30,
        )
        session_id = resp.json()["session_id"]

        # Delete
        resp2 = await client.delete(f"/v1/sessions/{session_id}")
        assert resp2.status_code == 200
        assert resp2.json()["deleted"] is True

        # Verify gone
        resp3 = await client.get(f"/v1/sessions/{session_id}")
        assert resp3.status_code == 404
