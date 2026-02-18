"""E2E test fixtures — real LLM calls against the example project workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway

EXAMPLE_WORKSPACE = Path(__file__).parent.parent.parent / "examples" / "test-project" / "workspace"

# Skip all e2e tests unless explicitly enabled
pytestmark = pytest.mark.e2e


def _require_gemini_key() -> str:
    """Return the Gemini API key or skip the test."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        pytest.skip("GEMINI_API_KEY not set — skipping e2e tests")
    return key


@pytest.fixture(scope="session")
def gemini_key() -> str:
    """Session-scoped Gemini API key check."""
    return _require_gemini_key()


@pytest.fixture
def gateway_app(gemini_key: str) -> Gateway:
    """Create a Gateway pointing at the example project workspace.

    Uses in-memory SQLite and disables telemetry for test isolation.
    """
    gw = Gateway(
        workspace=str(EXAMPLE_WORKSPACE),
        auth=False,
        title="E2E Test Gateway",
    )

    # Register the same code tools as the example app.py
    @gw.tool()
    async def echo(message: str) -> dict[str, Any]:
        """Echo a message back - for testing the tool pipeline."""
        return {"echo": message}

    @gw.tool()
    async def add_numbers(a: float, b: float) -> dict[str, Any]:
        """Add two numbers - for testing structured params."""
        return {"result": a + b}

    return gw


@pytest.fixture
async def client(gateway_app: Gateway) -> AsyncClient:
    """Async HTTP client wired to the gateway via ASGI transport."""
    async with gateway_app:
        transport = ASGITransport(app=gateway_app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac  # type: ignore[misc]
