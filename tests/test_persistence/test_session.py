"""Tests for persistence session management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from agent_gateway.config import PersistenceConfig
from agent_gateway.persistence.session import create_db_engine, create_session_factory, init_db


async def test_create_db_engine_sqlite(tmp_path):
    """Should create a working async SQLite engine."""
    db_path = tmp_path / "test.db"
    config = PersistenceConfig(url=f"sqlite+aiosqlite:///{db_path}")
    engine = create_db_engine(config)

    assert engine is not None
    # Verify we can connect
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("SELECT 1")
        assert result.scalar() == 1

    await engine.dispose()


async def test_create_session_factory_returns_sessions(db_engine: AsyncEngine):
    """Session factory should produce working sessions."""
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert session is not None
        # Session should work
        from sqlalchemy import text

        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


async def test_init_db_creates_tables(tmp_path):
    """init_db should create all tables in a fresh database."""
    db_path = tmp_path / "fresh.db"
    config = PersistenceConfig(url=f"sqlite+aiosqlite:///{db_path}")
    engine = create_db_engine(config)

    await init_db(engine)

    async with engine.connect() as conn:
        from sqlalchemy import inspect

        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "executions" in table_names
    assert "execution_steps" in table_names
    assert "audit_log" in table_names
    assert "schedules" in table_names

    await engine.dispose()


async def test_init_db_idempotent(db_engine: AsyncEngine):
    """init_db should be safe to call multiple times."""
    # db_engine already called init_db — calling again should not raise
    await init_db(db_engine)
