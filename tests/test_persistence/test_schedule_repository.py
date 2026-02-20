"""Tests for ScheduleRepository SQL implementation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_gateway.persistence.backends.sql.repository import ScheduleRepository
from agent_gateway.persistence.backends.sqlite import SqliteBackend
from agent_gateway.persistence.domain import ScheduleRecord


@pytest.fixture
async def sqlite_backend(tmp_path) -> SqliteBackend:
    db_path = tmp_path / "test_schedules.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()
    yield backend
    await backend.dispose()


@pytest.fixture
def schedule_repo(sqlite_backend: SqliteBackend) -> ScheduleRepository:
    return ScheduleRepository(sqlite_backend._session_factory)


def _make_record(
    schedule_id: str = "agent:daily",
    agent_id: str = "agent",
    name: str = "daily",
) -> ScheduleRecord:
    return ScheduleRecord(
        id=schedule_id,
        agent_id=agent_id,
        name=name,
        cron_expr="0 9 * * *",
        message="Run daily",
        created_at=datetime.now(UTC),
    )


async def test_upsert_and_get(schedule_repo: ScheduleRepository) -> None:
    record = _make_record()
    await schedule_repo.upsert(record)

    result = await schedule_repo.get("agent:daily")
    assert result is not None
    assert result.id == "agent:daily"
    assert result.agent_id == "agent"
    assert result.cron_expr == "0 9 * * *"


async def test_upsert_updates_existing(schedule_repo: ScheduleRepository) -> None:
    record = _make_record()
    await schedule_repo.upsert(record)

    record.cron_expr = "0 10 * * *"
    await schedule_repo.upsert(record)

    result = await schedule_repo.get("agent:daily")
    assert result is not None
    assert result.cron_expr == "0 10 * * *"


async def test_upsert_undeletes_record(schedule_repo: ScheduleRepository) -> None:
    record = _make_record()
    await schedule_repo.upsert(record)
    await schedule_repo.soft_delete("agent:daily")

    # Re-upsert should clear deleted_at
    await schedule_repo.upsert(record)
    result = await schedule_repo.get("agent:daily")
    assert result is not None
    assert result.deleted_at is None


async def test_get_nonexistent(schedule_repo: ScheduleRepository) -> None:
    result = await schedule_repo.get("nonexistent")
    assert result is None


async def test_list_all(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.upsert(_make_record("a:one", "a", "one"))
    await schedule_repo.upsert(_make_record("b:two", "b", "two"))

    results = await schedule_repo.list_all()
    assert len(results) == 2


async def test_list_all_excludes_deleted(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.upsert(_make_record("a:one", "a", "one"))
    await schedule_repo.upsert(_make_record("b:two", "b", "two"))
    await schedule_repo.soft_delete("a:one")

    results = await schedule_repo.list_all()
    assert len(results) == 1
    assert results[0].id == "b:two"


async def test_list_all_by_agent(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.upsert(_make_record("a:one", "a", "one"))
    await schedule_repo.upsert(_make_record("b:two", "b", "two"))

    results = await schedule_repo.list_all(agent_id="a")
    assert len(results) == 1
    assert results[0].agent_id == "a"


async def test_update_last_run(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.upsert(_make_record())
    now = datetime.now(UTC)
    await schedule_repo.update_last_run("agent:daily", now, now)

    result = await schedule_repo.get("agent:daily")
    assert result is not None
    assert result.last_run_at is not None
    assert result.next_run_at is not None


async def test_update_last_run_nonexistent(schedule_repo: ScheduleRepository) -> None:
    """update_last_run on missing record should not raise."""
    await schedule_repo.update_last_run("nonexistent", datetime.now(UTC), None)


async def test_update_next_run(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.upsert(_make_record())
    now = datetime.now(UTC)
    await schedule_repo.update_next_run("agent:daily", now)

    result = await schedule_repo.get("agent:daily")
    assert result is not None
    assert result.next_run_at is not None


async def test_update_next_run_nonexistent(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.update_next_run("nonexistent", datetime.now(UTC))


async def test_update_enabled(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.upsert(_make_record())
    await schedule_repo.update_enabled("agent:daily", False)

    result = await schedule_repo.get("agent:daily")
    assert result is not None
    assert result.enabled is False


async def test_update_enabled_nonexistent(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.update_enabled("nonexistent", False)


async def test_soft_delete(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.upsert(_make_record())
    await schedule_repo.soft_delete("agent:daily")

    result = await schedule_repo.get("agent:daily")
    assert result is not None
    assert result.deleted_at is not None


async def test_soft_delete_nonexistent(schedule_repo: ScheduleRepository) -> None:
    await schedule_repo.soft_delete("nonexistent")
