"""Unit tests for schedule API routes using a minimal Gateway."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway


def _write_gateway_yaml(workspace: Path) -> None:
    """Write a gateway.yaml that disables persistence so tests use NullScheduleRepository."""
    (workspace / "gateway.yaml").write_text("persistence:\n  enabled: false\n")


@pytest.fixture
def tmp_workspace_with_schedules(tmp_path: Path) -> Path:
    """Workspace with a scheduled agent."""
    agents = tmp_path / "agents"
    agents.mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()
    _write_gateway_yaml(tmp_path)

    agent_dir = agents / "test-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(
        "---\nschedules:\n  - name: my-job\n"
        '    cron: "0 9 * * *"\n    message: "Do work"\n'
        "    enabled: true\n---\n\n# Test Agent\n\nYou do work.\n"
    )
    return tmp_path


@pytest.fixture
def no_schedule_workspace(tmp_path: Path) -> Path:
    """Workspace with no scheduled agents."""
    agents = tmp_path / "agents"
    agents.mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()
    _write_gateway_yaml(tmp_path)

    agent_dir = agents / "plain-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("# Plain\n\nNo schedules.\n")
    return tmp_path


@pytest.fixture
async def client_with_schedules(
    tmp_workspace_with_schedules: Path,
) -> AsyncClient:
    gw = Gateway(workspace=str(tmp_workspace_with_schedules), auth=False)
    async with gw:
        transport = ASGITransport(app=gw)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac  # type: ignore[misc]


@pytest.fixture
async def client_no_schedules(no_schedule_workspace: Path) -> AsyncClient:
    gw = Gateway(workspace=str(no_schedule_workspace), auth=False)
    async with gw:
        transport = ASGITransport(app=gw)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac  # type: ignore[misc]


# --- Schedule list/detail ---


async def test_list_schedules(client_with_schedules: AsyncClient) -> None:
    resp = await client_with_schedules.get("/v1/schedules")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["id"] == "test-agent:my-job"


async def test_get_schedule_detail(client_with_schedules: AsyncClient) -> None:
    resp = await client_with_schedules.get("/v1/schedules/test-agent:my-job")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["agent_id"] == "test-agent"
    assert detail["cron_expr"] == "0 9 * * *"
    assert detail["message"] == "Do work"


async def test_get_schedule_not_found(client_with_schedules: AsyncClient) -> None:
    resp = await client_with_schedules.get("/v1/schedules/nonexistent:job")
    assert resp.status_code == 404


# --- Pause/resume/trigger ---


async def test_pause_schedule(client_with_schedules: AsyncClient) -> None:
    resp = await client_with_schedules.post("/v1/schedules/test-agent:my-job/pause")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"


async def test_pause_not_found(client_with_schedules: AsyncClient) -> None:
    resp = await client_with_schedules.post("/v1/schedules/nonexistent:job/pause")
    assert resp.status_code == 404


async def test_resume_not_found(client_with_schedules: AsyncClient) -> None:
    resp = await client_with_schedules.post("/v1/schedules/nonexistent:job/resume")
    assert resp.status_code == 404


async def test_trigger_not_found(client_with_schedules: AsyncClient) -> None:
    resp = await client_with_schedules.post("/v1/schedules/nonexistent:job/trigger")
    assert resp.status_code == 404


# --- Scheduler not active (no schedules in workspace) ---


async def test_pause_scheduler_not_active(client_no_schedules: AsyncClient) -> None:
    resp = await client_no_schedules.post("/v1/schedules/any:job/pause")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "scheduler_not_active"


async def test_resume_scheduler_not_active(client_no_schedules: AsyncClient) -> None:
    resp = await client_no_schedules.post("/v1/schedules/any:job/resume")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "scheduler_not_active"


async def test_trigger_scheduler_not_active(client_no_schedules: AsyncClient) -> None:
    resp = await client_no_schedules.post("/v1/schedules/any:job/trigger")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "scheduler_not_active"


async def test_list_schedules_empty_when_no_scheduler(
    client_no_schedules: AsyncClient,
) -> None:
    resp = await client_no_schedules.get("/v1/schedules")
    assert resp.status_code == 200
    assert resp.json() == []
