"""Tests for persistence backends — engine creation and table initialization."""

from __future__ import annotations

from sqlalchemy import inspect

from agent_gateway.persistence.backends.sqlite import SqliteBackend


async def test_sqlite_backend_creates_engine(tmp_path):
    """SqliteBackend should create a working async engine."""
    db_path = tmp_path / "test.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()

    async with backend._engine.connect() as conn:
        result = await conn.exec_driver_sql("SELECT 1")
        assert result.scalar() == 1

    await backend.dispose()


async def test_sqlite_backend_session_factory(tmp_path):
    """SqliteBackend session factory should produce working sessions."""
    db_path = tmp_path / "test.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()

    async with backend._session_factory() as session:
        from sqlalchemy import text

        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await backend.dispose()


async def test_sqlite_backend_creates_tables(tmp_path):
    """SqliteBackend.initialize should create all tables."""
    db_path = tmp_path / "test.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()

    async with backend._engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "executions" in table_names
    assert "execution_steps" in table_names
    assert "audit_log" in table_names
    assert "schedules" in table_names

    await backend.dispose()


async def test_sqlite_backend_initialize_idempotent(tmp_path):
    """initialize() should be safe to call multiple times."""
    db_path = tmp_path / "test.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()
    await backend.initialize()  # Should not raise
    await backend.dispose()


async def test_sqlite_backend_table_prefix(tmp_path):
    """SqliteBackend with table_prefix should prefix all table names."""
    db_path = tmp_path / "prefix_test.db"
    backend = SqliteBackend(path=str(db_path), table_prefix="ag_")
    await backend.initialize()

    async with backend._engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "ag_executions" in table_names
    assert "ag_execution_steps" in table_names
    assert "ag_audit_log" in table_names
    assert "ag_schedules" in table_names

    await backend.dispose()


async def test_sqlite_backend_memory(tmp_path):
    """SqliteBackend should support :memory: databases."""
    backend = SqliteBackend(path=":memory:")
    await backend.initialize()

    async with backend._engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "executions" in table_names
    await backend.dispose()
