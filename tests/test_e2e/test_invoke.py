"""E2E tests for agent invocation with real LLM calls."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


async def test_invoke_echo_tool(client: AsyncClient) -> None:
    """Invoke assistant with a message that should trigger the echo tool."""
    resp = await client.post(
        "/v1/agents/assistant/invoke",
        json={"message": "Use the echo tool to echo the word 'pineapple'"},
        timeout=30,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["agent_id"] == "assistant"
    assert data["usage"]["tool_calls"] >= 1
    assert "pineapple" in data["result"]["raw_text"].lower()


async def test_invoke_add_numbers(client: AsyncClient) -> None:
    """Invoke assistant with a math question to trigger add_numbers tool."""
    resp = await client.post(
        "/v1/agents/assistant/invoke",
        json={"message": "Use the add_numbers tool to compute 7 + 13. Return only the result."},
        timeout=30,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["usage"]["tool_calls"] >= 1
    assert "20" in data["result"]["raw_text"]


async def test_invoke_simple_greeting(client: AsyncClient) -> None:
    """Invoke assistant with a simple greeting — no tools expected."""
    resp = await client.post(
        "/v1/agents/assistant/invoke",
        json={"message": "Say hello in exactly one sentence."},
        timeout=30,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["result"]["raw_text"]  # Non-empty text
    assert data["usage"]["llm_calls"] >= 1


async def test_invoke_scheduled_reporter(client: AsyncClient) -> None:
    """Invoke the scheduled-reporter agent (no tools)."""
    resp = await client.post(
        "/v1/agents/scheduled-reporter/invoke",
        json={"message": "Generate a brief status report."},
        timeout=30,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["agent_id"] == "scheduled-reporter"
    assert data["result"]["raw_text"]


async def test_invoke_response_includes_execution_id(client: AsyncClient) -> None:
    """Invoke response includes execution_id and usage metrics."""
    resp = await client.post(
        "/v1/agents/assistant/invoke",
        json={"message": "Say 'ok'"},
        timeout=30,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"]
    assert "x-execution-id" in resp.headers
    assert data["usage"]["llm_calls"] >= 1
    assert data["usage"]["input_tokens"] > 0
    assert data["usage"]["output_tokens"] > 0
