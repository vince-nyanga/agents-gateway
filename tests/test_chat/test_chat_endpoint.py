"""Integration tests for the multi-turn chat endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.engine.llm import LLMResponse
from agent_gateway.engine.models import ToolCall
from agent_gateway.gateway import Gateway

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE_WORKSPACE = FIXTURES_DIR / "workspace"


def make_llm_response(
    text: str | None = None,
    tool_calls: list[ToolCall] | None = None,
    model: str = "gpt-4o-mini",
) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=tool_calls or [],
        model=model,
        input_tokens=10,
        output_tokens=20,
        cost=0.001,
    )


@pytest.fixture
def gateway_app() -> Gateway:
    gw = Gateway(
        workspace=str(FIXTURE_WORKSPACE),
        auth=False,
        title="Test Gateway",
    )

    @gw.tool()
    async def echo(message: str) -> dict[str, Any]:
        """Echo a message back."""
        return {"echo": message}

    @gw.tool()
    async def add_numbers(a: float, b: float) -> dict[str, Any]:
        """Add two numbers."""
        return {"result": a + b}

    return gw


@pytest.fixture
async def client(gateway_app: Gateway) -> AsyncClient:
    async with gateway_app:
        transport = ASGITransport(app=gateway_app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac  # type: ignore[misc]


def _mock_completion(responses: list[LLMResponse]) -> Any:
    call_count = 0

    async def _completion(*args: Any, **kwargs: Any) -> LLMResponse:
        nonlocal call_count
        if call_count >= len(responses):
            raise RuntimeError("No more mock responses")
        resp = responses[call_count]
        call_count += 1
        return resp

    return patch(
        "agent_gateway.engine.llm.LLMClient.completion",
        side_effect=_completion,
    )


class TestChatEndpoint:
    """Tests for POST /v1/agents/{agent_id}/chat."""

    async def test_new_session_created(self, client: AsyncClient) -> None:
        """Chat without session_id creates a new session."""
        with _mock_completion([make_llm_response(text="Hello!")]):
            resp = await client.post(
                "/v1/agents/test-agent/chat",
                json={"message": "Hi"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"].startswith("sess_")
        assert data["agent_id"] == "test-agent"
        assert data["status"] == "completed"
        assert data["result"]["raw_text"] == "Hello!"
        assert data["turn_count"] == 1

    async def test_multi_turn_conversation(self, client: AsyncClient) -> None:
        """Multiple messages with same session_id form a conversation."""
        # Turn 1
        with _mock_completion([make_llm_response(text="Hello! How can I help?")]):
            resp1 = await client.post(
                "/v1/agents/test-agent/chat",
                json={"message": "Hi there"},
            )
        assert resp1.status_code == 200
        session_id = resp1.json()["session_id"]
        assert resp1.json()["turn_count"] == 1

        # Turn 2
        with _mock_completion([make_llm_response(text="2 + 3 = 5")]):
            resp2 = await client.post(
                "/v1/agents/test-agent/chat",
                json={"message": "What is 2 + 3?", "session_id": session_id},
            )
        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == session_id
        assert resp2.json()["turn_count"] == 2

        # Turn 3
        with _mock_completion([make_llm_response(text="You're welcome!")]):
            resp3 = await client.post(
                "/v1/agents/test-agent/chat",
                json={"message": "Thanks!", "session_id": session_id},
            )
        assert resp3.status_code == 200
        assert resp3.json()["turn_count"] == 3

    async def test_session_not_found(self, client: AsyncClient) -> None:
        """Using a nonexistent session_id returns 404."""
        resp = await client.post(
            "/v1/agents/test-agent/chat",
            json={"message": "Hi", "session_id": "sess_nonexistent"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "session_not_found"

    async def test_agent_not_found(self, client: AsyncClient) -> None:
        """Chat with nonexistent agent returns 404."""
        resp = await client.post(
            "/v1/agents/nonexistent/chat",
            json={"message": "Hi"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "agent_not_found"

    async def test_tool_calls_in_chat(self, client: AsyncClient) -> None:
        """Tool calls work within multi-turn chat context."""
        responses = [
            # First: LLM calls add-numbers tool
            make_llm_response(
                tool_calls=[
                    ToolCall(name="add-numbers", arguments={"a": 2, "b": 3}, call_id="tc1")
                ]
            ),
            # Second: LLM gives final answer
            make_llm_response(text="The result of 2 + 3 is 5."),
        ]
        with _mock_completion(responses):
            resp = await client.post(
                "/v1/agents/test-agent/chat",
                json={"message": "What is 2 + 3?"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "5" in data["result"]["raw_text"]


class TestSessionCRUD:
    """Tests for session CRUD endpoints."""

    async def test_get_session(self, client: AsyncClient) -> None:
        """GET /v1/sessions/{id} returns session info."""
        # Create a session via chat
        with _mock_completion([make_llm_response(text="Hi!")]):
            resp = await client.post(
                "/v1/agents/test-agent/chat",
                json={"message": "Hello"},
            )
        session_id = resp.json()["session_id"]

        resp2 = await client.get(f"/v1/sessions/{session_id}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["session_id"] == session_id
        assert data["agent_id"] == "test-agent"
        assert data["turn_count"] == 1
        assert data["message_count"] >= 1
        # Timestamps should be Unix epoch (wall-clock, > year 2020)
        assert data["created_at"] > 1_577_836_800
        assert data["updated_at"] > 1_577_836_800

    async def test_get_session_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/sessions/nonexistent")
        assert resp.status_code == 404

    async def test_delete_session(self, client: AsyncClient) -> None:
        """DELETE /v1/sessions/{id} removes the session."""
        with _mock_completion([make_llm_response(text="Hi!")]):
            resp = await client.post(
                "/v1/agents/test-agent/chat",
                json={"message": "Hello"},
            )
        session_id = resp.json()["session_id"]

        # Delete it
        resp2 = await client.delete(f"/v1/sessions/{session_id}")
        assert resp2.status_code == 200
        assert resp2.json()["deleted"] is True

        # Now it should be gone
        resp3 = await client.get(f"/v1/sessions/{session_id}")
        assert resp3.status_code == 404

    async def test_delete_session_not_found(self, client: AsyncClient) -> None:
        resp = await client.delete("/v1/sessions/nonexistent")
        assert resp.status_code == 404

    async def test_list_sessions(self, client: AsyncClient) -> None:
        """GET /v1/sessions lists active sessions."""
        with _mock_completion([make_llm_response(text="Hi!")]):
            await client.post("/v1/agents/test-agent/chat", json={"message": "Hello"})
        with _mock_completion([make_llm_response(text="Hey!")]):
            await client.post("/v1/agents/test-agent/chat", json={"message": "Hey"})

        resp = await client.get("/v1/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) >= 2

    async def test_list_sessions_with_agent_filter(self, client: AsyncClient) -> None:
        """GET /v1/sessions?agent_id=X filters by agent."""
        with _mock_completion([make_llm_response(text="Hi!")]):
            await client.post("/v1/agents/test-agent/chat", json={"message": "Hello"})

        resp = await client.get("/v1/sessions?agent_id=test-agent")
        assert resp.status_code == 200
        sessions = resp.json()
        assert all(s["agent_id"] == "test-agent" for s in sessions)


class TestChatProgrammatic:
    """Tests for gw.chat() and programmatic session methods."""

    async def test_chat_programmatic(self, gateway_app: Gateway) -> None:
        """gw.chat() works for multi-turn conversations."""
        async with gateway_app:
            with _mock_completion([make_llm_response(text="Hello!")]):
                session_id, result = await gateway_app.chat("test-agent", "Hi")

            assert session_id.startswith("sess_")
            assert result.raw_text == "Hello!"
            assert result.duration_ms >= 0

            # Second turn with same session
            with _mock_completion([make_llm_response(text="Fine, thanks!")]):
                session_id2, result2 = await gateway_app.chat(
                    "test-agent", "How are you?", session_id=session_id
                )

            assert session_id2 == session_id
            assert result2.raw_text == "Fine, thanks!"

    async def test_chat_agent_not_found(self, gateway_app: Gateway) -> None:
        async with gateway_app:
            with pytest.raises(ValueError, match="not found"):
                await gateway_app.chat("nonexistent", "Hi")

    async def test_chat_session_not_found(self, gateway_app: Gateway) -> None:
        async with gateway_app:
            with pytest.raises(ValueError, match="not found"):
                await gateway_app.chat("test-agent", "Hi", session_id="sess_fake")

    async def test_programmatic_session_management(self, gateway_app: Gateway) -> None:
        """gw.get_session(), gw.list_sessions(), gw.delete_session() work."""
        async with gateway_app:
            with _mock_completion([make_llm_response(text="Hello!")]):
                session_id, _ = await gateway_app.chat("test-agent", "Hi")

            # get_session
            session = gateway_app.get_session(session_id)
            assert session is not None
            assert session.agent_id == "test-agent"
            assert session.turn_count == 1

            # list_sessions
            sessions = gateway_app.list_sessions()
            assert len(sessions) >= 1
            assert any(s.session_id == session_id for s in sessions)

            # list_sessions with filter
            filtered = gateway_app.list_sessions(agent_id="nonexistent")
            assert len(filtered) == 0

            # delete_session
            assert gateway_app.delete_session(session_id) is True
            assert gateway_app.get_session(session_id) is None
            assert gateway_app.delete_session(session_id) is False

    async def test_chat_session_mismatch(self, gateway_app: Gateway) -> None:
        """Using a session from one agent with a different agent raises ValueError."""
        async with gateway_app:
            # Create a session directly for a different agent ID
            session = gateway_app._session_store.create_session("other-agent")

            # Try to use it with test-agent
            with pytest.raises(ValueError, match="belongs to agent"):
                await gateway_app.chat("test-agent", "Hi", session_id=session.session_id)
