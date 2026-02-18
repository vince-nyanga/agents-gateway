"""Tests for SQLAlchemy persistence models."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_tables_created(db_engine: AsyncEngine):
    """init_db should create all expected tables."""
    async with db_engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "executions" in table_names
    assert "execution_steps" in table_names
    assert "audit_log" in table_names
    assert "schedules" in table_names


async def test_execution_columns(db_engine: AsyncEngine):
    """executions table should have all expected columns."""
    async with db_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("executions")}
        )

    expected = {
        "id",
        "agent_id",
        "status",
        "message",
        "context",
        "options",
        "result",
        "error",
        "usage",
        "started_at",
        "completed_at",
        "created_at",
    }
    assert expected.issubset(columns)


async def test_execution_steps_columns(db_engine: AsyncEngine):
    """execution_steps table should have all expected columns."""
    async with db_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("execution_steps")
            }
        )

    expected = {"id", "execution_id", "step_type", "sequence", "data", "duration_ms", "created_at"}
    assert expected.issubset(columns)


async def test_audit_log_columns(db_engine: AsyncEngine):
    """audit_log table should have all expected columns."""
    async with db_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("audit_log")}
        )

    expected = {
        "id",
        "event_type",
        "actor",
        "resource_type",
        "resource_id",
        "metadata",
        "ip_address",
        "created_at",
    }
    assert expected.issubset(columns)


async def test_schedules_columns(db_engine: AsyncEngine):
    """schedules table should have all expected columns."""
    async with db_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("schedules")}
        )

    expected = {
        "id",
        "agent_id",
        "name",
        "cron_expr",
        "message",
        "context",
        "enabled",
        "timezone",
        "last_run_at",
        "next_run_at",
        "created_at",
    }
    assert expected.issubset(columns)
