"""Tests for SchedulerEngine user schedule methods."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from agent_gateway.config import SchedulerConfig
from agent_gateway.persistence.null import NullExecutionRepository, NullScheduleRepository
from agent_gateway.queue.null import NullQueue
from agent_gateway.scheduler.engine import SchedulerEngine


def _make_engine(**overrides: Any) -> SchedulerEngine:
    """Create a SchedulerEngine with sensible test defaults."""
    config = overrides.pop("config", SchedulerConfig())
    schedule_repo = overrides.pop("schedule_repo", NullScheduleRepository())
    execution_repo = overrides.pop("execution_repo", NullExecutionRepository())
    queue = overrides.pop("queue", NullQueue())
    invoke_fn = overrides.pop("invoke_fn", AsyncMock())
    track_task = overrides.pop("track_task", lambda t: None)
    return SchedulerEngine(
        config=config,
        schedule_repo=schedule_repo,
        execution_repo=execution_repo,
        queue=queue,
        invoke_fn=invoke_fn,
        track_task=track_task,
        **overrides,
    )


class TestRegisterUserSchedule:
    async def test_register_adds_job(self) -> None:
        engine = _make_engine()
        # Start the engine first (it creates the APScheduler instance)
        await engine.start(agents={})

        await engine.register_user_schedule(
            schedule_id="user:sched-1",
            agent_id="agent-1",
            cron_expr="0 8 * * 1-5",
            message="Check inbox",
            timezone="UTC",
        )

        # Verify job was added to APScheduler
        assert engine._scheduler is not None
        job = engine._scheduler.get_job("user:sched-1")
        assert job is not None
        assert engine._agent_map["user:sched-1"] == "agent-1"

        await engine.stop()

    async def test_register_with_input_data(self) -> None:
        engine = _make_engine()
        await engine.start(agents={})

        await engine.register_user_schedule(
            schedule_id="user:sched-2",
            agent_id="agent-1",
            cron_expr="*/5 * * * *",
            message="Status check",
            input_data={"topic": "sales"},
            timezone="US/Eastern",
        )

        job = engine._scheduler.get_job("user:sched-2")
        assert job is not None
        # Check input_data was merged with source metadata
        kwargs = job.kwargs
        assert kwargs["input"]["source"] == "user_scheduled"
        assert kwargs["input"]["topic"] == "sales"

        await engine.stop()

    async def test_register_disabled_schedule(self) -> None:
        engine = _make_engine()
        await engine.start(agents={})

        await engine.register_user_schedule(
            schedule_id="user:sched-3",
            agent_id="agent-1",
            cron_expr="0 8 * * *",
            message="Daily briefing",
            enabled=False,
        )

        job = engine._scheduler.get_job("user:sched-3")
        assert job is not None
        # When disabled, the job is paused (next_run_time is None)
        assert job.next_run_time is None

        await engine.stop()

    async def test_register_with_notify_config(self) -> None:
        engine = _make_engine()
        await engine.start(agents={})

        notify = {"webhook": {"url": "https://example.com/hook"}}
        await engine.register_user_schedule(
            schedule_id="user:sched-4",
            agent_id="agent-1",
            cron_expr="0 9 * * *",
            message="Morning report",
            notify=notify,
        )

        job = engine._scheduler.get_job("user:sched-4")
        assert job is not None
        assert job.kwargs["input"]["_notify_config"] == notify

        await engine.stop()

    async def test_register_when_scheduler_none(self) -> None:
        engine = _make_engine()
        # Don't start — _scheduler is None
        await engine.register_user_schedule(
            schedule_id="user:sched-5",
            agent_id="agent-1",
            cron_expr="0 8 * * *",
            message="test",
        )
        # Should not raise, just early-return


class TestRemoveUserSchedule:
    async def test_remove_existing_schedule(self) -> None:
        engine = _make_engine()
        await engine.start(agents={})

        # Register first
        await engine.register_user_schedule(
            schedule_id="user:sched-1",
            agent_id="agent-1",
            cron_expr="0 8 * * *",
            message="test",
        )
        assert engine._scheduler.get_job("user:sched-1") is not None

        # Remove
        await engine.remove_user_schedule("user:sched-1")
        assert engine._scheduler.get_job("user:sched-1") is None
        assert "user:sched-1" not in engine._agent_map

        await engine.stop()

    async def test_remove_nonexistent_schedule(self) -> None:
        engine = _make_engine()
        await engine.start(agents={})

        # Should not raise
        await engine.remove_user_schedule("nonexistent")

        await engine.stop()

    async def test_remove_when_scheduler_none(self) -> None:
        engine = _make_engine()
        # Don't start
        await engine.remove_user_schedule("any-id")
        # Should not raise
