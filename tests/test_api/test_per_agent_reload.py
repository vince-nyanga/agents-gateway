"""Hot-reload behaviour tests for per-agent typed invoke routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway

AGENT_WITH_INPUT = """\
---
description: Has input schema.
input_schema:
  type: object
  properties:
    q:
      type: string
  required: [q]
---

# Agent
"""

AGENT_WITHOUT_INPUT = """\
---
description: No schema.
---

# Agent
"""


def _write_agent(ws: Path, agent_id: str, body: str) -> None:
    d = ws / "agents" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "AGENT.md").write_text(body)


@pytest.mark.asyncio
async def test_reload_adds_and_removes_per_agent_route(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    _write_agent(ws, "shifty", AGENT_WITH_INPUT)

    gw = Gateway(workspace=str(ws), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Initially the typed route exists.
            spec = (await ac.get("/openapi.json")).json()
            assert "/v1/agents/shifty/invoke" in spec["paths"]

            # Remove the schema on disk.
            _write_agent(ws, "shifty", AGENT_WITHOUT_INPUT)
            await gw.reload()

            # The typed route should now be gone; generic route still serves it.
            spec = (await ac.get("/openapi.json")).json()
            assert "/v1/agents/shifty/invoke" not in spec["paths"]
            assert "/v1/agents/{agent_id}/invoke" in spec["paths"]

            # Add the schema back.
            _write_agent(ws, "shifty", AGENT_WITH_INPUT)
            await gw.reload()
            spec = (await ac.get("/openapi.json")).json()
            assert "/v1/agents/shifty/invoke" in spec["paths"]
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_reload_updates_request_shape(tmp_path: Path) -> None:
    """Changing the input schema reflects immediately after reload."""
    ws = tmp_path / "workspace"
    _write_agent(ws, "mut", AGENT_WITH_INPUT)

    gw = Gateway(workspace=str(ws), auth=False)
    await gw._startup()
    try:
        transport = ASGITransport(app=gw)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Old schema requires 'q'
            resp = await ac.post(
                "/v1/agents/mut/invoke",
                json={"message": "hi", "input": {}},
            )
            assert resp.status_code == 422

            # New schema requires 'topic'
            new_agent = """\
---
description: Has new schema.
input_schema:
  type: object
  properties:
    topic:
      type: string
  required: [topic]
---

# Agent
"""
            _write_agent(ws, "mut", new_agent)
            await gw.reload()

            # Providing old 'q' now fails, 'topic' passes validation.
            resp = await ac.post(
                "/v1/agents/mut/invoke",
                json={"message": "hi", "input": {"q": "x"}},
            )
            assert resp.status_code == 422
    finally:
        await gw._shutdown()


@pytest.mark.asyncio
async def test_router_order_preserved_after_reload(tmp_path: Path) -> None:
    """Per-agent routes must come before the parameterized route."""
    ws = tmp_path / "workspace"
    _write_agent(ws, "ordered", AGENT_WITH_INPUT)

    gw = Gateway(workspace=str(ws), auth=False)
    await gw._startup()
    try:
        await gw.reload()
        # Scan the router: the literal per-agent route should appear before
        # the parameterized one in registration order.
        literal_idx = None
        param_idx = None
        for idx, route in enumerate(gw.router.routes):
            name = getattr(route, "name", None)
            if name == "invoke_agent__ordered":
                literal_idx = idx
            elif name == "invoke_agent":
                param_idx = idx

        assert literal_idx is not None, "literal per-agent route not found"
        assert param_idx is not None, "generic invoke route not found"
        assert literal_idx < param_idx, (
            f"literal route (idx={literal_idx}) must precede parameterized "
            f"route (idx={param_idx}) so Starlette matches it first"
        )
    finally:
        await gw._shutdown()
