"""Integration test: programmatic invocation via gw.invoke()."""

from __future__ import annotations

from typing import Any

import pytest

from agent_gateway.engine.models import StopReason
from agent_gateway.gateway import Gateway

from .conftest import FIXTURE_WORKSPACE, make_llm_response


async def test_programmatic_invoke(mock_llm_completion: Any) -> None:
    """gw.invoke() works without HTTP."""
    async with Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False) as gw:
        responses = [make_llm_response(text="Hello from programmatic!")]
        with mock_llm_completion(responses):
            result = await gw.invoke("test-agent", "Hi")

        assert result.stop_reason == StopReason.COMPLETED
        assert result.raw_text == "Hello from programmatic!"


async def test_programmatic_invoke_unknown_agent() -> None:
    """gw.invoke() with unknown agent raises ValueError."""
    async with Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False) as gw:
        with pytest.raises(ValueError, match="not found"):
            await gw.invoke("nonexistent", "Hi")


async def test_programmatic_invoke_with_tools(mock_llm_completion: Any) -> None:
    """gw.invoke() executes tools and returns result."""
    from agent_gateway.engine.models import ToolCall

    gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)

    @gw.tool()
    async def echo(message: str) -> dict[str, str]:
        """Echo a message back."""
        return {"echo": message}

    async with gw:
        responses = [
            make_llm_response(
                tool_calls=[ToolCall(name="echo", arguments={"message": "World"}, call_id="c1")]
            ),
            make_llm_response(text="I echoed World for you."),
        ]
        with mock_llm_completion(responses):
            result = await gw.invoke("test-agent", "Echo World")

        assert result.stop_reason == StopReason.COMPLETED
        assert result.usage.tool_calls == 1


async def test_reload_workspace() -> None:
    """gw.reload() refreshes workspace state."""
    async with Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False) as gw:
        assert gw.workspace is not None
        old_agents = set(gw.workspace.agents.keys())

        await gw.reload()

        assert gw.workspace is not None
        assert set(gw.workspace.agents.keys()) == old_agents


async def test_reload_endpoint() -> None:
    """POST /v1/reload re-scans workspace."""
    from httpx import ASGITransport, AsyncClient

    gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, reload=True)
    async with gw:
        transport = ASGITransport(app=gw)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/v1/reload")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agents"] >= 1
