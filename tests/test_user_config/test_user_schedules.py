"""Tests for UserScheduleRecord domain model and UserScheduleRepository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_gateway.persistence.domain import UserScheduleRecord
from agent_gateway.persistence.null import NullUserScheduleRepository


class TestUserScheduleRecordModel:
    """Test the UserScheduleRecord dataclass."""

    def test_defaults(self) -> None:
        record = UserScheduleRecord(
            id="sched-1",
            user_id="user-1",
            agent_id="agent-1",
            name="morning-check",
            cron_expr="0 8 * * 1-5",
            message="Check inbox",
        )
        assert record.enabled is True
        assert record.timezone == "UTC"
        assert record.input is None
        assert record.notify is None
        assert record.last_run_at is None

    def test_with_all_fields(self) -> None:
        now = datetime.now(UTC)
        record = UserScheduleRecord(
            id="sched-1",
            user_id="user-1",
            agent_id="agent-1",
            name="morning-check",
            cron_expr="0 8 * * 1-5",
            message="Check inbox",
            input={"folder": "INBOX"},
            enabled=False,
            timezone="US/Eastern",
            notify={"webhook": "https://example.com/hook"},
            last_run_at=now,
            next_run_at=now,
            created_at=now,
        )
        assert record.enabled is False
        assert record.timezone == "US/Eastern"
        assert record.notify is not None


class TestNullUserScheduleRepository:
    """Test the null implementation."""

    @pytest.fixture
    def repo(self) -> NullUserScheduleRepository:
        return NullUserScheduleRepository()

    async def test_create_is_noop(self, repo: NullUserScheduleRepository) -> None:
        record = UserScheduleRecord(
            id="s-1",
            user_id="u-1",
            agent_id="a-1",
            name="test",
            cron_expr="* * * * *",
            message="test",
        )
        await repo.create(record)  # should not raise

    async def test_get_returns_none(self, repo: NullUserScheduleRepository) -> None:
        result = await repo.get("s-1")
        assert result is None

    async def test_list_by_user_returns_empty(self, repo: NullUserScheduleRepository) -> None:
        assert await repo.list_by_user("u-1") == []

    async def test_delete_returns_false(self, repo: NullUserScheduleRepository) -> None:
        assert await repo.delete("s-1") is False

    async def test_update_enabled_is_noop(self, repo: NullUserScheduleRepository) -> None:
        await repo.update_enabled("s-1", False)  # should not raise

    async def test_update_last_run_is_noop(self, repo: NullUserScheduleRepository) -> None:
        now = datetime.now(UTC)
        await repo.update_last_run("s-1", now, now)  # should not raise


class TestUserScheduleSqlRepository:
    """Test SQL repository with in-memory SQLite."""

    @pytest.fixture
    async def repo(self):
        """Create an in-memory SQLite backend and return the user schedule repo."""
        from agent_gateway.persistence.backends.sqlite import SqliteBackend

        backend = SqliteBackend(path=":memory:")
        await backend.initialize()
        yield backend.user_schedule_repo
        await backend.dispose()

    async def test_create_and_get(self, repo) -> None:
        now = datetime.now(UTC)
        record = UserScheduleRecord(
            id="sched-1",
            user_id="user-1",
            agent_id="agent-1",
            name="morning-check",
            cron_expr="0 8 * * 1-5",
            message="Check inbox",
            input={"folder": "INBOX"},
            enabled=True,
            timezone="US/Eastern",
            created_at=now,
        )
        await repo.create(record)
        result = await repo.get("sched-1")
        assert result is not None
        assert result.user_id == "user-1"
        assert result.agent_id == "agent-1"
        assert result.name == "morning-check"
        assert result.cron_expr == "0 8 * * 1-5"

    async def test_list_by_user(self, repo) -> None:
        now = datetime.now(UTC)
        for i in range(3):
            await repo.create(
                UserScheduleRecord(
                    id=f"sched-{i}",
                    user_id="user-1",
                    agent_id="agent-1",
                    name=f"schedule-{i}",
                    cron_expr="* * * * *",
                    message="test",
                    created_at=now,
                )
            )
        # Different user
        await repo.create(
            UserScheduleRecord(
                id="sched-other",
                user_id="user-2",
                agent_id="agent-1",
                name="other",
                cron_expr="* * * * *",
                message="test",
                created_at=now,
            )
        )
        results = await repo.list_by_user("user-1")
        assert len(results) == 3

    async def test_update_enabled(self, repo) -> None:
        now = datetime.now(UTC)
        await repo.create(
            UserScheduleRecord(
                id="sched-1",
                user_id="user-1",
                agent_id="agent-1",
                name="test",
                cron_expr="* * * * *",
                message="test",
                enabled=True,
                created_at=now,
            )
        )
        await repo.update_enabled("sched-1", False)
        result = await repo.get("sched-1")
        assert result is not None
        assert result.enabled is False

    async def test_update_enabled_nonexistent(self, repo) -> None:
        # Should not raise for nonexistent schedule
        await repo.update_enabled("nonexistent", False)

    async def test_update_last_run(self, repo) -> None:
        now = datetime.now(UTC)
        await repo.create(
            UserScheduleRecord(
                id="sched-1",
                user_id="user-1",
                agent_id="agent-1",
                name="test",
                cron_expr="* * * * *",
                message="test",
                created_at=now,
            )
        )
        await repo.update_last_run("sched-1", now, now)
        result = await repo.get("sched-1")
        assert result is not None
        assert result.last_run_at is not None

    async def test_update_last_run_nonexistent(self, repo) -> None:
        now = datetime.now(UTC)
        await repo.update_last_run("nonexistent", now, now)

    async def test_delete(self, repo) -> None:
        now = datetime.now(UTC)
        await repo.create(
            UserScheduleRecord(
                id="sched-1",
                user_id="user-1",
                agent_id="agent-1",
                name="test",
                cron_expr="* * * * *",
                message="test",
                created_at=now,
            )
        )
        assert await repo.delete("sched-1") is True
        assert await repo.get("sched-1") is None
        assert await repo.delete("sched-1") is False
