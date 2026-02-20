"""Tests for the SchedulerEngine."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agent_gateway.config import SchedulerConfig
from agent_gateway.persistence.null import NullScheduleRepository
from agent_gateway.queue.null import NullQueue
from agent_gateway.scheduler.engine import SchedulerEngine
from agent_gateway.workspace.agent import AgentDefinition, ScheduleConfig


def _make_agent(
    agent_id: str = "reporter",
    schedules: list[ScheduleConfig] | None = None,
) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        path=MagicMock(),
        agent_prompt="You are a reporter.",
        schedules=schedules or [],
    )


def _make_schedule(
    name: str = "daily-report",
    cron: str = "0 9 * * *",
    message: str = "Generate report",
    enabled: bool = True,
    timezone: str | None = None,
) -> ScheduleConfig:
    return ScheduleConfig(
        name=name,
        cron=cron,
        message=message,
        enabled=enabled,
        timezone=timezone,
    )


def _make_config(**overrides: Any) -> SchedulerConfig:
    return SchedulerConfig(**overrides)


def _make_schedule_repo() -> NullScheduleRepository:
    return NullScheduleRepository()


def _make_engine(
    execution_repo: AsyncMock | None = None,
    queue: Any | None = None,
    invoke_fn: AsyncMock | None = None,
    schedule_repo: NullScheduleRepository | None = None,
    config: SchedulerConfig | None = None,
    timezone: str = "UTC",
) -> SchedulerEngine:
    """Build a SchedulerEngine with sensible test defaults."""
    return SchedulerEngine(
        config=config or _make_config(),
        schedule_repo=schedule_repo or _make_schedule_repo(),
        execution_repo=execution_repo or AsyncMock(),
        queue=queue if queue is not None else NullQueue(),
        invoke_fn=invoke_fn or AsyncMock(),
        track_task=lambda t: None,
        timezone=timezone,
    )


class TestSchedulerEngineStart:
    async def test_start_registers_jobs(self) -> None:
        """Scheduler should register APScheduler jobs for each schedule."""
        sched = _make_schedule()
        agent = _make_agent(schedules=[sched])

        engine = _make_engine()

        await engine.start(
            schedules=[sched],
            agents={"reporter": agent},
        )

        # Scheduler should be running
        assert engine._scheduler is not None
        assert engine._scheduler.running

        # Job should be registered
        job = engine._scheduler.get_job("reporter:daily-report")
        assert job is not None

        await engine.stop()

    async def test_start_pauses_disabled_schedule(self) -> None:
        """Disabled schedules should be registered but paused."""
        sched = _make_schedule(enabled=False)
        agent = _make_agent(schedules=[sched])

        engine = _make_engine()

        await engine.start(schedules=[sched], agents={"reporter": agent})

        job = engine._scheduler.get_job("reporter:daily-report")
        assert job is not None
        # Paused jobs have next_run_time == None
        assert job.next_run_time is None

        await engine.stop()

    async def test_start_with_multiple_agents(self) -> None:
        """Multiple agents with schedules should all be registered."""
        sched1 = _make_schedule(name="daily")
        sched2 = _make_schedule(name="hourly", cron="0 * * * *")
        agent1 = _make_agent(agent_id="agent-a", schedules=[sched1])
        agent2 = _make_agent(agent_id="agent-b", schedules=[sched2])

        engine = _make_engine()

        await engine.start(
            schedules=[sched1, sched2],
            agents={"agent-a": agent1, "agent-b": agent2},
        )

        assert engine._scheduler.get_job("agent-a:daily") is not None
        assert engine._scheduler.get_job("agent-b:hourly") is not None

        await engine.stop()

    async def test_start_timezone_inheritance(self) -> None:
        """Schedules without explicit timezone should inherit gateway default."""
        sched = _make_schedule(timezone=None)
        agent = _make_agent(schedules=[sched])

        engine = _make_engine(timezone="America/New_York")
        await engine.start(schedules=[sched], agents={"reporter": agent})

        job = engine._scheduler.get_job("reporter:daily-report")
        assert job is not None
        # next_run_time should be timezone-aware with New York
        assert str(job.next_run_time.tzinfo) != "UTC"

        await engine.stop()

    async def test_start_explicit_utc_honored(self) -> None:
        """Schedules with explicit timezone=UTC should use UTC even when gateway is non-UTC."""
        sched = _make_schedule(timezone="UTC")
        agent = _make_agent(schedules=[sched])

        engine = _make_engine(timezone="America/New_York")
        await engine.start(schedules=[sched], agents={"reporter": agent})

        job = engine._scheduler.get_job("reporter:daily-report")
        assert job is not None
        assert str(job.next_run_time.tzinfo) == "UTC"

        await engine.stop()


class TestSchedulerEnginePauseResume:
    async def test_pause_schedule(self) -> None:
        sched = _make_schedule()
        agent = _make_agent(schedules=[sched])

        engine = _make_engine()
        await engine.start(schedules=[sched], agents={"reporter": agent})

        ok = await engine.pause("reporter:daily-report")
        assert ok is True

        job = engine._scheduler.get_job("reporter:daily-report")
        assert job.next_run_time is None  # paused

        await engine.stop()

    async def test_resume_schedule(self) -> None:
        sched = _make_schedule(enabled=False)
        agent = _make_agent(schedules=[sched])

        engine = _make_engine()
        await engine.start(schedules=[sched], agents={"reporter": agent})

        ok = await engine.resume("reporter:daily-report")
        assert ok is True

        job = engine._scheduler.get_job("reporter:daily-report")
        assert job.next_run_time is not None  # resumed

        await engine.stop()

    async def test_pause_nonexistent_returns_false(self) -> None:
        engine = _make_engine()
        await engine.start(schedules=[], agents={})

        ok = await engine.pause("nonexistent:schedule")
        assert ok is False

        await engine.stop()


class TestSchedulerEngineTrigger:
    async def test_trigger_returns_execution_id(self) -> None:
        invoke_fn = AsyncMock()
        execution_repo = AsyncMock()
        sched = _make_schedule()
        agent = _make_agent(schedules=[sched])

        engine = _make_engine(invoke_fn=invoke_fn, execution_repo=execution_repo)
        await engine.start(schedules=[sched], agents={"reporter": agent})

        execution_id = await engine.trigger("reporter:daily-report")
        assert execution_id is not None
        assert isinstance(execution_id, str)

        # Wait for background task
        await asyncio.sleep(0.1)

        await engine.stop()

    async def test_trigger_nonexistent_returns_none(self) -> None:
        engine = _make_engine()
        await engine.start(schedules=[], agents={})

        result = await engine.trigger("nonexistent:schedule")
        assert result is None

        await engine.stop()


class TestSchedulerEngineOverlap:
    async def test_overlap_prevention(self) -> None:
        """Second fire of same schedule should be skipped while first is active."""
        execution_repo = AsyncMock()
        sched = _make_schedule()
        agent = _make_agent(schedules=[sched])

        engine = _make_engine(execution_repo=execution_repo)
        await engine.start(schedules=[sched], agents={"reporter": agent})

        # Simulate first execution marking active
        async with engine._active_lock:
            engine._active_scheduled["reporter:daily-report"] = time.monotonic()

        # Second dispatch should skip (overlap detected)
        await engine.dispatch_scheduled_execution(
            schedule_id="reporter:daily-report",
            agent_id="reporter",
            message="Generate report",
            context={"source": "scheduled"},
        )

        # No execution record should be created (overlap skipped)
        execution_repo.create.assert_not_called()

        await engine.stop()

    async def test_on_execution_complete_clears_active(self) -> None:
        engine = _make_engine()
        await engine.start(schedules=[], agents={})

        engine._active_scheduled["reporter:daily-report"] = time.monotonic()
        await engine.on_execution_complete("reporter:daily-report")
        assert "reporter:daily-report" not in engine._active_scheduled

        await engine.stop()

    async def test_safety_valve_clears_stuck_schedule(self) -> None:
        """Stuck schedules should be force-cleared after timeout."""
        execution_repo = AsyncMock()
        sched = _make_schedule()
        agent = _make_agent(schedules=[sched])

        engine = _make_engine(
            execution_repo=execution_repo,
            config=_make_config(misfire_grace_seconds=1),
        )
        await engine.start(schedules=[sched], agents={"reporter": agent})

        # Simulate stuck execution (fire time far in the past)
        engine._active_scheduled["reporter:daily-report"] = time.monotonic() - 10

        # Should force-clear and proceed (timeout = 2 * 1s = 2s, elapsed = 10s)
        await engine.dispatch_scheduled_execution(
            schedule_id="reporter:daily-report",
            agent_id="reporter",
            message="Generate report",
            context={"source": "scheduled"},
        )

        # Should have created an execution record (not skipped)
        execution_repo.create.assert_called_once()

        await engine.stop()


class TestSchedulerEngineGetSchedules:
    async def test_get_schedules_returns_list(self) -> None:
        sched = _make_schedule()
        agent = _make_agent(schedules=[sched])

        engine = _make_engine()
        await engine.start(schedules=[sched], agents={"reporter": agent})

        schedules = await engine.get_schedules()
        assert isinstance(schedules, list)

        await engine.stop()

    async def test_get_schedule_detail(self) -> None:
        sched = _make_schedule()
        agent = _make_agent(schedules=[sched])

        engine = _make_engine()
        await engine.start(schedules=[sched], agents={"reporter": agent})

        detail = await engine.get_schedule("reporter:daily-report")
        assert detail is not None
        assert detail["id"] == "reporter:daily-report"
        assert detail["agent_id"] == "reporter"
        assert detail["name"] == "daily-report"
        assert detail["cron_expr"] == "0 9 * * *"

        await engine.stop()

    async def test_get_schedule_nonexistent_returns_none(self) -> None:
        engine = _make_engine()
        await engine.start(schedules=[], agents={})

        detail = await engine.get_schedule("nonexistent")
        assert detail is None

        await engine.stop()


class TestSchedulerEngineStop:
    async def test_stop_shuts_down_apscheduler(self) -> None:
        engine = _make_engine()
        await engine.start(schedules=[], agents={})
        assert engine._scheduler is not None

        await engine.stop()
        assert engine._scheduler is None
