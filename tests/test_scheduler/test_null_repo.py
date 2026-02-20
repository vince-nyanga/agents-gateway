"""Tests for NullScheduleRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_gateway.persistence.domain import ScheduleRecord
from agent_gateway.persistence.null import NullScheduleRepository


async def test_null_schedule_upsert() -> None:
    repo = NullScheduleRepository()
    record = ScheduleRecord(
        id="agent:daily",
        agent_id="agent",
        name="daily",
        cron_expr="0 9 * * *",
        message="Run daily",
        created_at=datetime.now(UTC),
    )
    await repo.upsert(record)
    result = await repo.get("agent:daily")
    assert result is not None
    assert result.id == "agent:daily"


async def test_null_schedule_list_all() -> None:
    repo = NullScheduleRepository()
    record = ScheduleRecord(
        id="agent:daily",
        agent_id="agent",
        name="daily",
        cron_expr="0 9 * * *",
        message="Run daily",
        created_at=datetime.now(UTC),
    )
    await repo.upsert(record)
    results = await repo.list_all()
    assert len(results) == 1


async def test_null_schedule_update_last_run() -> None:
    repo = NullScheduleRepository()
    record = ScheduleRecord(
        id="agent:daily",
        agent_id="agent",
        name="daily",
        cron_expr="0 9 * * *",
        message="Run daily",
        created_at=datetime.now(UTC),
    )
    await repo.upsert(record)

    now = datetime.now(UTC)
    await repo.update_last_run("agent:daily", now, now)

    result = await repo.get("agent:daily")
    assert result is not None
    assert result.last_run_at == now


async def test_null_schedule_update_enabled() -> None:
    repo = NullScheduleRepository()
    record = ScheduleRecord(
        id="agent:daily",
        agent_id="agent",
        name="daily",
        cron_expr="0 9 * * *",
        message="Run daily",
        created_at=datetime.now(UTC),
    )
    await repo.upsert(record)

    await repo.update_enabled("agent:daily", False)
    result = await repo.get("agent:daily")
    assert result is not None
    assert result.enabled is False


async def test_null_schedule_update_next_run() -> None:
    repo = NullScheduleRepository()
    record = ScheduleRecord(
        id="agent:daily",
        agent_id="agent",
        name="daily",
        cron_expr="0 9 * * *",
        message="Run daily",
        created_at=datetime.now(UTC),
    )
    await repo.upsert(record)

    now = datetime.now(UTC)
    await repo.update_next_run("agent:daily", now)

    result = await repo.get("agent:daily")
    assert result is not None
    assert result.next_run_at == now
