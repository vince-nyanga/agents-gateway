"""Integration tests for per-agent typed invoke routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from agent_gateway.engine.llm import LLMResponse
from agent_gateway.exceptions import ConfigError
from agent_gateway.gateway import Gateway

AGENT_INPUT_ONLY = """\
---
description: Agent with input schema only.
input_schema:
  type: object
  properties:
    query:
      type: string
  required: [query]
---

# Input Only Agent
"""

AGENT_OUTPUT_ONLY = """\
---
description: Agent with output schema only.
output_schema:
  type: object
  properties:
    answer:
      type: string
  required: [answer]
---

# Output Only Agent
"""

AGENT_BOTH = """\
---
description: Agent with input and output schemas.
input_schema:
  type: object
  properties:
    x:
      type: integer
  required: [x]
output_schema:
  type: object
  properties:
    y:
      type: integer
  required: [y]
---

# Both Agent
"""

AGENT_NEITHER = """\
# Plain Agent

No schemas.
"""


@pytest.fixture
def workspace_with_schemas(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    for name, body in [
        ("agent-a", AGENT_INPUT_ONLY),
        ("agent-b", AGENT_OUTPUT_ONLY),
        ("agent-c", AGENT_BOTH),
        ("agent-d", AGENT_NEITHER),
    ]:
        d = ws / "agents" / name
        d.mkdir(parents=True)
        (d / "AGENT.md").write_text(body)
    return ws


def _mock_llm(text: str = '{"y": 42}') -> Any:
    async def _completion(*args: Any, **kwargs: Any) -> LLMResponse:
        return LLMResponse(
            text=text, tool_calls=[], model="gpt-4o-mini", input_tokens=1, output_tokens=1, cost=0
        )

    return patch("agent_gateway.engine.llm.LLMClient.completion", side_effect=_completion)


@pytest.mark.asyncio
async def test_openapi_lists_per_agent_paths(workspace_with_schemas: Path) -> None:
    gw = Gateway(workspace=str(workspace_with_schemas), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/openapi.json")
            spec = resp.json()
            paths = set(spec["paths"].keys())
            assert "/v1/agents/agent-a/invoke" in paths  # input-only
            assert "/v1/agents/agent-b/invoke" in paths  # output-only
            assert "/v1/agents/agent-c/invoke" in paths  # both
            assert "/v1/agents/{agent_id}/invoke" in paths  # generic
            # agent-d has no schema; only covered by the generic route.
            assert "/v1/agents/agent-d/invoke" not in paths

            # Schema components are agent-prefixed to avoid collisions.
            components = spec.get("components", {}).get("schemas", {})
            assert "InvokeRequest_agent_a" in components
            assert "InvokeResponse_agent_b" in components
            assert "InvokeRequest_agent_c" in components
            assert "InvokeResponse_agent_c" in components
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_invalid_input_returns_envelope_422(workspace_with_schemas: Path) -> None:
    gw = Gateway(workspace=str(workspace_with_schemas), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # missing required 'query'
            resp = await ac.post(
                "/v1/agents/agent-a/invoke",
                json={"message": "hi", "input": {}},
            )
            assert resp.status_code == 422
            body = resp.json()
            assert body["error"]["code"] == "input_validation_failed"
            assert "Input validation failed" in body["error"]["message"]
            assert isinstance(body["error"]["details"], list)
            assert len(body["error"]["details"]) >= 1
            # Field-level details are preserved.
            assert any(
                "query" in ".".join(str(p) for p in d.get("loc", []))
                for d in body["error"]["details"]
            )
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_valid_input_passes_validation(workspace_with_schemas: Path) -> None:
    gw = Gateway(workspace=str(workspace_with_schemas), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with _mock_llm(text='{"y": 7}'):
                resp = await ac.post(
                    "/v1/agents/agent-c/invoke",
                    json={"message": "hi", "input": {"x": 1}},
                )
                # Success (or at least past validation)
                assert resp.status_code in (200, 201)
                body = resp.json()
                assert body["agent_id"] == "agent-c"
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_generic_route_still_used_for_schemaless_agents(
    workspace_with_schemas: Path,
) -> None:
    gw = Gateway(workspace=str(workspace_with_schemas), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with _mock_llm(text="hello"):
                resp = await ac.post(
                    "/v1/agents/agent-d/invoke",
                    json={"message": "hi"},
                )
                # agent-d has no schema — served by generic route.
                assert resp.status_code == 200
                body = resp.json()
                assert body["agent_id"] == "agent-d"
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_generic_422_envelope_unaffected(tmp_path: Path) -> None:
    """Non-per-agent routes still get FastAPI's default 422 envelope."""
    ws = tmp_path / "ws"
    d = ws / "agents" / "plain"
    d.mkdir(parents=True)
    (d / "AGENT.md").write_text(AGENT_NEITHER)

    gw = Gateway(workspace=str(ws), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Hit a route that requires a body (/v1/agents/x/invoke) with
            # bad JSON. This goes through the generic route, which does
            # not appear in _per_agent_invoke_paths — our handler defers
            # to FastAPI's default, which returns {'detail': [...]}.
            resp = await ac.post(
                "/v1/agents/plain/invoke",
                # Missing required 'message' field.
                json={},
            )
            assert resp.status_code == 422
            body = resp.json()
            # FastAPI default envelope uses 'detail', not our 'error' wrapper.
            assert "detail" in body
            assert "error" not in body
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_set_schema_after_startup_raises(workspace_with_schemas: Path) -> None:
    gw = Gateway(workspace=str(workspace_with_schemas), auth=False)
    await gw._startup()
    try:

        class Foo(BaseModel):
            x: int

        with pytest.raises(ConfigError, match="gw.reload"):
            gw.set_input_schema("agent-d", Foo)
        with pytest.raises(ConfigError, match="gw.reload"):
            gw.set_output_schema("agent-d", Foo)
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_programmatic_pydantic_class_is_bound_directly(tmp_path: Path) -> None:
    """gw.set_input_schema(agent, Model) uses Model verbatim (no JSON round-trip)."""
    ws = tmp_path / "ws"
    d = ws / "agents" / "researcher"
    d.mkdir(parents=True)
    (d / "AGENT.md").write_text(AGENT_NEITHER)

    class ResearchInput(BaseModel):
        topic: str
        depth: int = 1

    gw = Gateway(workspace=str(ws), auth=False)
    gw.set_input_schema("researcher", ResearchInput)
    await gw._startup()
    try:
        # After startup, the agent carries the exact class.
        agent = gw.agents["researcher"]
        assert agent._pydantic_input_model is ResearchInput

        # OpenAPI lists the per-agent path.
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/openapi.json")
            paths = set(resp.json()["paths"].keys())
            assert "/v1/agents/researcher/invoke" in paths
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_startup_tolerates_bad_schema(tmp_path: Path) -> None:
    """An agent whose schema fails conversion still gets the generic route."""
    # A schema that's valid JSON but pathological for the generator
    # (using ``not`` at root with a non-object).
    bad_agent = """\
---
description: Bad schema.
input_schema:
  not: {type: string}
---

# Bad
"""
    ws = tmp_path / "ws"
    d = ws / "agents" / "bad"
    d.mkdir(parents=True)
    (d / "AGENT.md").write_text(bad_agent)

    # Good agent to prove startup continues.
    g = ws / "agents" / "good"
    g.mkdir(parents=True)
    (g / "AGENT.md").write_text(AGENT_INPUT_ONLY)

    gw = Gateway(workspace=str(ws), auth=False)
    # Must not raise
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/openapi.json")
            paths = set(resp.json()["paths"].keys())
            # generic route always present
            assert "/v1/agents/{agent_id}/invoke" in paths
            # good agent typed route
            assert "/v1/agents/good/invoke" in paths
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_concurrent_requests_during_snapshot_safe(
    workspace_with_schemas: Path,
) -> None:
    """Verify concurrent requests don't observe a torn router state.

    Regression guard: the router mutation must happen synchronously under
    the reload lock; there should be no interleaving where a request gets
    a 404 for a route that exists on both sides of the reload.
    """
    gw = Gateway(workspace=str(workspace_with_schemas), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:

            async def hit_openapi() -> int:
                r = await ac.get("/openapi.json")
                return r.status_code

            async def reload_once() -> None:
                await gw.reload()

            # Kick off many simultaneous openapi fetches while reloading
            # multiple times.
            tasks = [hit_openapi() for _ in range(20)] + [reload_once() for _ in range(5)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    raise r
                if isinstance(r, int):
                    assert r == 200
    finally:
        await gw._shutdown()
