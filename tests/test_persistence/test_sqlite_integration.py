"""SQLite integration tests — mirrors test_postgres_integration.py.

Verifies table creation, prefix, full CRUD lifecycle, and idempotent init
against a real SQLite database (via tmp_path).
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from agent_gateway.persistence.backends.sql.repository import (
    AuditRepository,
    ExecutionRepository,
)
from agent_gateway.persistence.backends.sqlite import SqliteBackend
from agent_gateway.persistence.domain import ExecutionRecord, ExecutionStep


@pytest.fixture
async def sqlite_backend(tmp_path) -> SqliteBackend:
    """Function-scoped SQLite backend with fresh database per test."""
    db_path = tmp_path / "test.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()
    yield backend
    await backend.dispose()


# ── Table creation ──────────────────────────────────────────────────


async def test_sqlite_backend_creates_tables(sqlite_backend: SqliteBackend):
    """SqliteBackend.initialize should create all four tables."""
    async with sqlite_backend._engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "executions" in table_names
    assert "execution_steps" in table_names
    assert "audit_log" in table_names
    assert "schedules" in table_names


async def test_sqlite_backend_table_prefix(tmp_path):
    """Tables should be created with the specified prefix."""
    db_path = tmp_path / "prefix.db"
    backend = SqliteBackend(path=str(db_path), table_prefix="myapp_")
    await backend.initialize()
    try:
        async with backend._engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )

        assert "myapp_executions" in table_names
        assert "myapp_execution_steps" in table_names
        assert "myapp_audit_log" in table_names
        assert "myapp_schedules" in table_names
    finally:
        await backend.dispose()


# ── Execution CRUD ──────────────────────────────────────────────────


async def test_sqlite_execution_crud(sqlite_backend: SqliteBackend):
    """Full CRUD lifecycle: create, get, update_status, update_result, list_by_agent."""
    repo = ExecutionRepository(sqlite_backend._session_factory)

    # Create
    record = ExecutionRecord(
        id="sq-exec-001",
        agent_id="test-agent",
        status="running",
        message="Hello from SQLite",
    )
    await repo.create(record)

    # Get
    fetched = await repo.get("sq-exec-001")
    assert fetched is not None
    assert fetched.id == "sq-exec-001"
    assert fetched.agent_id == "test-agent"
    assert fetched.status == "running"
    assert fetched.message == "Hello from SQLite"

    # Update status
    await repo.update_status("sq-exec-001", "completed")
    fetched = await repo.get("sq-exec-001")
    assert fetched is not None
    assert fetched.status == "completed"

    # Update result
    result = {"output": "Done!", "raw_text": "Done!"}
    usage = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001}
    await repo.update_result("sq-exec-001", result, usage)
    fetched = await repo.get("sq-exec-001")
    assert fetched is not None
    assert fetched.result == result
    assert fetched.usage == usage
    assert fetched.completed_at is not None

    # List by agent
    results = await repo.list_by_agent("test-agent")
    assert len(results) == 1
    assert results[0].id == "sq-exec-001"


async def test_sqlite_get_nonexistent(sqlite_backend: SqliteBackend):
    """Should return None for missing execution."""
    repo = ExecutionRepository(sqlite_backend._session_factory)
    result = await repo.get("does-not-exist")
    assert result is None


async def test_sqlite_list_by_agent_limit(sqlite_backend: SqliteBackend):
    """Should respect the limit parameter."""
    repo = ExecutionRepository(sqlite_backend._session_factory)

    for i in range(5):
        record = ExecutionRecord(
            id=f"sq-limit-{i}",
            agent_id="limit-agent",
            status="completed",
            message=f"Message {i}",
        )
        await repo.create(record)

    results = await repo.list_by_agent("limit-agent", limit=2)
    assert len(results) == 2


# ── Execution steps ─────────────────────────────────────────────────


async def test_sqlite_execution_steps(sqlite_backend: SqliteBackend):
    """Should add an execution step and retrieve via get."""
    repo = ExecutionRepository(sqlite_backend._session_factory)

    record = ExecutionRecord(
        id="sq-step-001",
        agent_id="test-agent",
        status="running",
        message="Test",
    )
    await repo.create(record)

    step = ExecutionStep(
        execution_id="sq-step-001",
        step_type="llm_call",
        sequence=1,
        data={"model": "gpt-4o-mini", "tokens": 100},
        duration_ms=500,
    )
    await repo.add_step(step)

    fetched = await repo.get("sq-step-001")
    assert fetched is not None


# ── Audit CRUD ──────────────────────────────────────────────────────


async def test_sqlite_audit_crud(sqlite_backend: SqliteBackend):
    """Should write and retrieve audit log entries."""
    repo = AuditRepository(sqlite_backend._session_factory)

    await repo.log(
        event_type="execution.started",
        actor="api-key-1",
        resource_type="execution",
        resource_id="exec-001",
        metadata={"agent_id": "test-agent"},
        ip_address="127.0.0.1",
    )

    entries = await repo.list_recent(limit=10)
    assert len(entries) == 1
    assert entries[0].event_type == "execution.started"
    assert entries[0].actor == "api-key-1"
    assert entries[0].resource_id == "exec-001"
    assert entries[0].ip_address == "127.0.0.1"


async def test_sqlite_audit_multiple(sqlite_backend: SqliteBackend):
    """Should retrieve multiple audit entries."""
    repo = AuditRepository(sqlite_backend._session_factory)

    for i in range(3):
        await repo.log(event_type=f"event-{i}", actor=f"actor-{i}")

    entries = await repo.list_recent(limit=10)
    assert len(entries) == 3


# ── Idempotent initialize ──────────────────────────────────────────


async def test_sqlite_idempotent_initialize(tmp_path):
    """initialize() should be safe to call multiple times."""
    db_path = tmp_path / "idempotent.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()
    await backend.initialize()  # Should not raise
    await backend.dispose()


# ── Memory mode ─────────────────────────────────────────────────────


async def test_sqlite_memory_backend():
    """SqliteBackend should support :memory: databases."""
    backend = SqliteBackend(path=":memory:")
    await backend.initialize()

    async with backend._engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "executions" in table_names
    assert "execution_steps" in table_names
    assert "audit_log" in table_names
    assert "schedules" in table_names
    await backend.dispose()
