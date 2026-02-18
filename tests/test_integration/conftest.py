"""Shared fixtures for integration tests."""

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
    """Create a mock LLM response."""
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
    """Create a Gateway app with the test fixture workspace."""
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
    """Create an async test client for the gateway."""
    async with gateway_app:
        transport = ASGITransport(app=gateway_app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac  # type: ignore[misc]


async def make_test_client(gw: Gateway) -> AsyncClient:
    """Create a test client with startup triggered. Caller must close both."""
    await gw._startup()
    transport = ASGITransport(app=gw)  # type: ignore[arg-type]
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def mock_llm_completion() -> Any:
    """Patch LLMClient.completion to return mock responses."""

    def _mock(responses: list[LLMResponse]) -> Any:
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

    return _mock
