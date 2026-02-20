"""Tests for Gateway schedule delegate methods."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_gateway.gateway import Gateway


def _write_gateway_yaml(workspace: Path) -> None:
    """Write a gateway.yaml that disables persistence so tests use NullScheduleRepository."""
    (workspace / "gateway.yaml").write_text("persistence:\n  enabled: false\n")


@pytest.fixture
def no_schedule_workspace(tmp_path: Path) -> Path:
    agents = tmp_path / "agents"
    agents.mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()
    _write_gateway_yaml(tmp_path)

    agent_dir = agents / "plain"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("# Plain\n\nNo schedules.\n")
    return tmp_path


@pytest.fixture
def schedule_workspace(tmp_path: Path) -> Path:
    agents = tmp_path / "agents"
    agents.mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()
    _write_gateway_yaml(tmp_path)

    agent_dir = agents / "cron-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(
        "---\nschedules:\n  - name: hourly\n"
        '    cron: "0 * * * *"\n    message: "Run"\n'
        "    enabled: true\n---\n\n# Cron Agent\n\nDo scheduled work.\n"
    )
    return tmp_path


async def test_scheduler_property_none_without_schedules(
    no_schedule_workspace: Path,
) -> None:
    gw = Gateway(workspace=str(no_schedule_workspace), auth=False)
    async with gw:
        assert gw.scheduler is None


async def test_scheduler_property_set_with_schedules(
    schedule_workspace: Path,
) -> None:
    gw = Gateway(workspace=str(schedule_workspace), auth=False)
    async with gw:
        assert gw.scheduler is not None


async def test_list_schedules_empty_when_no_scheduler(
    no_schedule_workspace: Path,
) -> None:
    gw = Gateway(workspace=str(no_schedule_workspace), auth=False)
    async with gw:
        result = await gw.list_schedules()
        assert result == []


async def test_get_schedule_none_when_no_scheduler(
    no_schedule_workspace: Path,
) -> None:
    gw = Gateway(workspace=str(no_schedule_workspace), auth=False)
    async with gw:
        result = await gw.get_schedule("any:id")
        assert result is None


async def test_pause_schedule_false_when_no_scheduler(
    no_schedule_workspace: Path,
) -> None:
    gw = Gateway(workspace=str(no_schedule_workspace), auth=False)
    async with gw:
        result = await gw.pause_schedule("any:id")
        assert result is False


async def test_resume_schedule_false_when_no_scheduler(
    no_schedule_workspace: Path,
) -> None:
    gw = Gateway(workspace=str(no_schedule_workspace), auth=False)
    async with gw:
        result = await gw.resume_schedule("any:id")
        assert result is False


async def test_trigger_schedule_none_when_no_scheduler(
    no_schedule_workspace: Path,
) -> None:
    gw = Gateway(workspace=str(no_schedule_workspace), auth=False)
    async with gw:
        result = await gw.trigger_schedule("any:id")
        assert result is None


async def test_list_schedules_returns_data(schedule_workspace: Path) -> None:
    gw = Gateway(workspace=str(schedule_workspace), auth=False)
    async with gw:
        result = await gw.list_schedules()
        assert len(result) == 1
        assert result[0]["id"] == "cron-agent:hourly"


async def test_get_schedule_returns_detail(schedule_workspace: Path) -> None:
    gw = Gateway(workspace=str(schedule_workspace), auth=False)
    async with gw:
        result = await gw.get_schedule("cron-agent:hourly")
        assert result is not None
        assert result["cron_expr"] == "0 * * * *"


async def test_pause_and_resume_schedule(schedule_workspace: Path) -> None:
    gw = Gateway(workspace=str(schedule_workspace), auth=False)
    async with gw:
        ok = await gw.pause_schedule("cron-agent:hourly")
        assert ok is True

        ok = await gw.resume_schedule("cron-agent:hourly")
        assert ok is True
