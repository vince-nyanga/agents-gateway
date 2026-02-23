"""Tests for database migration infrastructure."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from agent_gateway.persistence.migrations.runner import (
    get_current_revision,
    run_downgrade,
    run_upgrade,
)


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        url = f"sqlite:///{f.name}"
    engine = create_engine(url)
    yield engine
    engine.dispose()
    Path(f.name).unlink(missing_ok=True)


def test_upgrade_creates_all_tables(tmp_db) -> None:
    """upgrade('head') creates the full schema."""
    with tmp_db.connect() as conn:
        run_upgrade(conn, "head")
        conn.commit()

    inspector = inspect(tmp_db)
    tables = set(inspector.get_table_names())
    expected = {
        "alembic_version",
        "executions",
        "execution_steps",
        "audit_log",
        "schedules",
        "users",
        "conversations",
        "conversation_messages",
        "memories",
        "user_agent_configs",
        "user_schedules",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_current_revision_after_upgrade(tmp_db) -> None:
    """After upgrade head, current revision is '002'."""
    with tmp_db.connect() as conn:
        run_upgrade(conn, "head")
        conn.commit()

    with tmp_db.connect() as conn:
        rev = get_current_revision(conn)
    assert rev == "005"


def test_downgrade_removes_tables(tmp_db) -> None:
    """downgrade('base') removes all tables."""
    with tmp_db.connect() as conn:
        run_upgrade(conn, "head")
        conn.commit()

    with tmp_db.connect() as conn:
        run_downgrade(conn, "base")
        conn.commit()

    inspector = inspect(tmp_db)
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert len(tables) == 0, f"Tables remaining after downgrade: {tables}"


def test_upgrade_is_idempotent(tmp_db) -> None:
    """Running upgrade twice doesn't fail."""
    with tmp_db.connect() as conn:
        run_upgrade(conn, "head")
        conn.commit()

    with tmp_db.connect() as conn:
        run_upgrade(conn, "head")
        conn.commit()

    with tmp_db.connect() as conn:
        rev = get_current_revision(conn)
    assert rev == "005"


def test_current_revision_on_empty_db(tmp_db) -> None:
    """Current revision is None on a fresh database."""
    with tmp_db.connect() as conn:
        rev = get_current_revision(conn)
    assert rev is None


class TestDbCliCommands:
    """Test the db CLI subcommands appear in help."""

    def test_db_help(self) -> None:
        from typer.testing import CliRunner

        from agent_gateway.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["db", "--help"])
        assert result.exit_code == 0
        assert "upgrade" in result.output
        assert "downgrade" in result.output
        assert "current" in result.output
        assert "history" in result.output
