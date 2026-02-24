"""Tests for dashboard execution filtering: date range, cost range, error search, polling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_gateway.persistence.backends.sql.repository import ExecutionRepository
from agent_gateway.persistence.backends.sqlite import SqliteBackend
from agent_gateway.persistence.domain import ExecutionRecord
from agent_gateway.persistence.null import NullExecutionRepository


@pytest.fixture
async def sqlite_backend(tmp_path):  # type: ignore[no-untyped-def]
    db_path = tmp_path / "test_filters.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()
    yield backend
    await backend.dispose()


@pytest.fixture
async def session_factory(
    sqlite_backend: SqliteBackend,
) -> async_sessionmaker[AsyncSession]:
    return sqlite_backend._session_factory


@pytest.fixture
async def repo(session_factory: async_sessionmaker[AsyncSession]) -> ExecutionRepository:
    return ExecutionRepository(session_factory)


@pytest.fixture
async def seeded_repo(repo: ExecutionRepository) -> ExecutionRepository:
    """Seed repo with executions at various dates and costs."""
    now = datetime.now(UTC)
    records = [
        ExecutionRecord(
            id="exec-old",
            agent_id="agent-a",
            status="completed",
            message="Old execution",
            created_at=now - timedelta(days=10),
            usage={"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50},
        ),
        ExecutionRecord(
            id="exec-mid",
            agent_id="agent-a",
            status="completed",
            message="Mid execution",
            created_at=now - timedelta(days=3),
            usage={"cost_usd": 0.50, "input_tokens": 500, "output_tokens": 200},
        ),
        ExecutionRecord(
            id="exec-new",
            agent_id="agent-b",
            status="failed",
            message="New execution",
            error="Connection timeout error",
            created_at=now - timedelta(hours=1),
            usage={"cost_usd": 1.20, "input_tokens": 1000, "output_tokens": 400},
        ),
        ExecutionRecord(
            id="exec-running",
            agent_id="agent-a",
            status="running",
            message="Running now",
            created_at=now,
            usage=None,
        ),
    ]
    for r in records:
        await repo.create(r)
    return repo


async def test_date_from_filter(seeded_repo: ExecutionRepository) -> None:
    """Executions before date_from are excluded."""
    since = datetime.now(UTC) - timedelta(days=5)
    results = await seeded_repo.list_all(since=since)
    ids = {r.id for r in results}
    assert "exec-old" not in ids
    assert "exec-mid" in ids
    assert "exec-new" in ids


async def test_date_to_filter(seeded_repo: ExecutionRepository) -> None:
    """Executions after until are excluded (inclusive boundary for the day)."""
    until = datetime.now(UTC) - timedelta(days=2)
    results = await seeded_repo.list_all(until=until)
    ids = {r.id for r in results}
    assert "exec-old" in ids
    assert "exec-mid" in ids
    assert "exec-new" not in ids
    assert "exec-running" not in ids


async def test_min_cost_filter(seeded_repo: ExecutionRepository) -> None:
    """Cheap executions are excluded by min_cost."""
    results = await seeded_repo.list_all(min_cost=0.40)
    ids = {r.id for r in results}
    assert "exec-old" not in ids
    assert "exec-mid" in ids
    assert "exec-new" in ids


async def test_max_cost_filter(seeded_repo: ExecutionRepository) -> None:
    """Expensive executions are excluded by max_cost."""
    results = await seeded_repo.list_all(max_cost=0.60)
    ids = {r.id for r in results}
    assert "exec-old" in ids
    assert "exec-mid" in ids
    assert "exec-new" not in ids


async def test_combined_date_and_status_filter(seeded_repo: ExecutionRepository) -> None:
    """Combined date + status filter works."""
    since = datetime.now(UTC) - timedelta(days=5)
    results = await seeded_repo.list_all(since=since, status="completed")
    ids = {r.id for r in results}
    assert ids == {"exec-mid"}


async def test_search_matches_error_field(seeded_repo: ExecutionRepository) -> None:
    """Search should match the error field."""
    results = await seeded_repo.list_all(search="timeout error")
    ids = {r.id for r in results}
    assert "exec-new" in ids


async def test_count_all_with_new_filters(seeded_repo: ExecutionRepository) -> None:
    """count_all should respect the new filter params."""
    count = await seeded_repo.count_all(min_cost=0.40)
    assert count == 2  # exec-mid and exec-new

    count = await seeded_repo.count_all(
        until=datetime.now(UTC) - timedelta(days=2),
    )
    assert count == 2  # exec-old and exec-mid


async def test_null_repo_accepts_new_kwargs() -> None:
    """NullExecutionRepository.list_all/count_all accept new kwargs without raising."""
    repo = NullExecutionRepository()
    result = await repo.list_all(
        until=datetime.now(UTC),
        min_cost=0.01,
        max_cost=1.00,
    )
    assert result == []

    count = await repo.count_all(
        until=datetime.now(UTC),
        min_cost=0.01,
        max_cost=1.00,
    )
    assert count == 0


async def test_polling_interval_is_5s() -> None:
    """The executions template polling div should use every 5s."""
    import importlib.resources

    template_ref = (
        importlib.resources.files("agent_gateway.dashboard")
        / "templates"
        / "dashboard"
        / "executions.html"
    )
    with importlib.resources.as_file(template_ref) as p:
        content = p.read_text()
    assert "every 5s" in content
    assert "every 10s" not in content
