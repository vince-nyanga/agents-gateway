"""E2E tests for schedule management and trigger with real LLM calls."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


async def test_list_schedules(client: AsyncClient) -> None:
    """GET /v1/schedules returns the scheduled-reporter schedule."""
    resp = await client.get("/v1/schedules")
    assert resp.status_code == 200
    schedules = resp.json()
    assert isinstance(schedules, list)
    assert len(schedules) >= 1

    ids = [s["id"] for s in schedules]
    assert "scheduled-reporter:daily-report" in ids

    sched = next(s for s in schedules if s["id"] == "scheduled-reporter:daily-report")
    assert sched["agent_id"] == "scheduled-reporter"
    assert sched["name"] == "daily-report"
    assert sched["cron_expr"] == "0 9 * * 1-5"


async def test_get_schedule_detail(client: AsyncClient) -> None:
    """GET /v1/schedules/{id} returns full detail for a schedule."""
    resp = await client.get("/v1/schedules/scheduled-reporter:daily-report")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == "scheduled-reporter:daily-report"
    assert detail["agent_id"] == "scheduled-reporter"
    assert detail["cron_expr"] == "0 9 * * 1-5"
    assert detail["enabled"] is True
    assert detail["timezone"] == "Europe/London"


async def test_get_schedule_not_found(client: AsyncClient) -> None:
    """GET /v1/schedules/{id} returns 404 for unknown schedule."""
    resp = await client.get("/v1/schedules/nonexistent:schedule")
    assert resp.status_code == 404


async def test_pause_and_resume_schedule(client: AsyncClient) -> None:
    """POST pause/resume toggles the schedule state."""
    schedule_id = "scheduled-reporter:daily-report"

    # Pause
    resp = await client.post(f"/v1/schedules/{schedule_id}/pause")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    # Verify paused via detail
    resp = await client.get(f"/v1/schedules/{schedule_id}")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Resume
    resp = await client.post(f"/v1/schedules/{schedule_id}/resume")
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"

    # Verify resumed
    resp = await client.get(f"/v1/schedules/{schedule_id}")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


async def test_trigger_schedule_produces_execution(client: AsyncClient) -> None:
    """POST trigger fires the schedule and produces a completed execution."""
    schedule_id = "scheduled-reporter:daily-report"

    # Trigger
    resp = await client.post(f"/v1/schedules/{schedule_id}/trigger")
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "triggered"
    assert data["execution_id"]

    execution_id = data["execution_id"]

    # Poll until completed (max 30s)
    for _ in range(30):
        resp = await client.get(f"/v1/executions/{execution_id}")
        assert resp.status_code == 200
        execution = resp.json()
        if execution["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(1.0)
    else:
        pytest.fail(f"Execution {execution_id} did not complete within 30s")

    assert execution["status"] == "completed"
    assert execution["agent_id"] == "scheduled-reporter"
    assert execution["result"]["raw_text"]  # Should have generated a report


async def test_trigger_nonexistent_returns_404(client: AsyncClient) -> None:
    """POST trigger on unknown schedule returns 404."""
    resp = await client.post("/v1/schedules/nonexistent:schedule/trigger")
    assert resp.status_code == 404
