"""PostgreSQL integration tests using testcontainers.

Requires Docker to be running. Skipped automatically when Docker is unavailable.
Run with: uv run pytest -m postgres
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import inspect, text

from agent_gateway.persistence.backends.postgres import PostgresBackend
from agent_gateway.persistence.backends.sql.repository import (
    AuditRepository,
    ExecutionRepository,
)
from agent_gateway.persistence.domain import ExecutionRecord, ExecutionStep

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="session")
def postgres_container():
    """Session-scoped PostgreSQL container — starts once, shared by all tests."""
    # Disable Ryuk reaper to avoid port-mapping issues in some Docker setups
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")

    # testcontainers returns postgresql+psycopg2:// — swap driver to asyncpg
    url = container.get_connection_url()
    url = url.replace("+psycopg2", "+asyncpg", 1)
    yield url
    container.stop()


@pytest.fixture
async def postgres_backend(postgres_container: str):
    """Function-scoped backend with a unique table prefix per test."""
    prefix = f"t{uuid.uuid4().hex[:8]}_"
    backend = PostgresBackend(url=postgres_container, table_prefix=prefix)
    await backend.initialize()
    yield backend
    await backend.dispose()


# ── Table creation ──────────────────────────────────────────────────


async def test_postgres_backend_creates_tables(postgres_backend: PostgresBackend):
    """PostgresBackend.initialize should create all four tables."""
    async with postgres_backend._engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    expected = {"executions", "execution_steps", "audit_log", "schedules"}
    # Tables are prefixed — check that each base name appears (with prefix)
    for base in expected:
        assert any(base in t for t in table_names), f"Missing table containing '{base}'"


async def test_postgres_backend_table_prefix(postgres_container: str):
    """Tables should be created with the specified prefix."""
    backend = PostgresBackend(url=postgres_container, table_prefix="myapp_")
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


async def test_postgres_backend_schema(postgres_container: str):
    """Tables should be created inside the specified schema."""
    from sqlalchemy.ext.asyncio import create_async_engine

    schema_name = f"test_{uuid.uuid4().hex[:8]}"

    # Create the schema first
    engine = create_async_engine(postgres_container)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema_name}"))
    await engine.dispose()

    backend = PostgresBackend(url=postgres_container, schema=schema_name)
    await backend.initialize()
    try:
        async with backend._engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names(schema=schema_name)
            )

        assert "executions" in table_names
        assert "execution_steps" in table_names
        assert "audit_log" in table_names
        assert "schedules" in table_names
    finally:
        await backend.dispose()


# ── DSN normalization ───────────────────────────────────────────────


async def test_postgres_backend_dsn_normalization(postgres_container: str):
    """Both postgres:// and postgresql:// should be normalized to postgresql+asyncpg://."""
    # Test with the real container URL but different prefix each time to avoid mapper conflicts
    cases = [
        ("postgres://", "postgresql+asyncpg://"),
        ("postgresql://", "postgresql+asyncpg://"),
        ("postgresql+asyncpg://", "postgresql+asyncpg://"),
    ]

    for input_scheme, expected_scheme in cases:
        # Swap the scheme in the container URL
        url = postgres_container
        # Container URL starts with postgresql+asyncpg://
        test_url = url.replace("postgresql+asyncpg://", input_scheme, 1)
        prefix = f"dsn{uuid.uuid4().hex[:8]}_"
        backend = PostgresBackend(url=test_url, table_prefix=prefix)
        assert expected_scheme in str(backend._engine.url), (
            f"Expected {expected_scheme} in URL for input scheme {input_scheme}"
        )
        await backend.dispose()


# ── Execution CRUD ──────────────────────────────────────────────────


async def test_postgres_execution_crud(postgres_backend: PostgresBackend):
    """Full CRUD lifecycle: create, get, update_status, update_result, list_by_agent."""
    repo = ExecutionRepository(postgres_backend._session_factory)

    # Create
    record = ExecutionRecord(
        id="pg-exec-001",
        agent_id="test-agent",
        status="running",
        message="Hello from Postgres",
    )
    await repo.create(record)

    # Get
    fetched = await repo.get("pg-exec-001")
    assert fetched is not None
    assert fetched.id == "pg-exec-001"
    assert fetched.agent_id == "test-agent"
    assert fetched.status == "running"
    assert fetched.message == "Hello from Postgres"

    # Update status
    await repo.update_status("pg-exec-001", "completed")
    fetched = await repo.get("pg-exec-001")
    assert fetched is not None
    assert fetched.status == "completed"

    # Update result
    result = {"output": "Done!", "raw_text": "Done!"}
    usage = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001}
    await repo.update_result("pg-exec-001", result, usage)
    fetched = await repo.get("pg-exec-001")
    assert fetched is not None
    assert fetched.result == result
    assert fetched.usage == usage
    assert fetched.completed_at is not None

    # List by agent
    results = await repo.list_by_agent("test-agent")
    assert len(results) == 1
    assert results[0].id == "pg-exec-001"


async def test_postgres_get_nonexistent(postgres_backend: PostgresBackend):
    """Should return None for missing execution."""
    repo = ExecutionRepository(postgres_backend._session_factory)
    result = await repo.get("does-not-exist")
    assert result is None


async def test_postgres_list_by_agent_limit(postgres_backend: PostgresBackend):
    """Should respect the limit parameter."""
    repo = ExecutionRepository(postgres_backend._session_factory)

    for i in range(5):
        record = ExecutionRecord(
            id=f"pg-limit-{i}",
            agent_id="limit-agent",
            status="completed",
            message=f"Message {i}",
        )
        await repo.create(record)

    results = await repo.list_by_agent("limit-agent", limit=2)
    assert len(results) == 2


# ── Execution steps ─────────────────────────────────────────────────


async def test_postgres_execution_steps(postgres_backend: PostgresBackend):
    """Should add an execution step and retrieve via get."""
    repo = ExecutionRepository(postgres_backend._session_factory)

    record = ExecutionRecord(
        id="pg-step-001",
        agent_id="test-agent",
        status="running",
        message="Test",
    )
    await repo.create(record)

    step = ExecutionStep(
        execution_id="pg-step-001",
        step_type="llm_call",
        sequence=1,
        data={"model": "gpt-4o-mini", "tokens": 100},
        duration_ms=500,
    )
    await repo.add_step(step)

    fetched = await repo.get("pg-step-001")
    assert fetched is not None


# ── Audit CRUD ──────────────────────────────────────────────────────


async def test_postgres_audit_crud(postgres_backend: PostgresBackend):
    """Should write and retrieve audit log entries."""
    repo = AuditRepository(postgres_backend._session_factory)

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


async def test_postgres_audit_multiple(postgres_backend: PostgresBackend):
    """Should retrieve multiple audit entries."""
    repo = AuditRepository(postgres_backend._session_factory)

    for i in range(3):
        await repo.log(event_type=f"event-{i}", actor=f"actor-{i}")

    entries = await repo.list_recent(limit=10)
    assert len(entries) == 3


# ── Idempotent initialize ──────────────────────────────────────────


async def test_postgres_idempotent_initialize(postgres_container: str):
    """initialize() should be safe to call multiple times."""
    prefix = f"t{uuid.uuid4().hex[:8]}_"
    backend = PostgresBackend(url=postgres_container, table_prefix=prefix)
    await backend.initialize()
    await backend.initialize()  # Should not raise
    await backend.dispose()
