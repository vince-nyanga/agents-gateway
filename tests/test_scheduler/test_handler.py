"""Tests for the scheduler handler module."""

from __future__ import annotations

from unittest.mock import AsyncMock

from agent_gateway.scheduler.handler import run_scheduled_job, set_scheduler_engine


async def test_run_scheduled_job_dispatches() -> None:
    """Handler should dispatch to the scheduler engine."""
    engine = AsyncMock()
    engine.dispatch_scheduled_execution = AsyncMock()

    set_scheduler_engine(engine)
    try:
        await run_scheduled_job(
            schedule_id="agent:daily",
            agent_id="agent",
            message="hello",
            input={"source": "scheduled"},
        )
        engine.dispatch_scheduled_execution.assert_called_once_with(
            schedule_id="agent:daily",
            agent_id="agent",
            message="hello",
            input={"source": "scheduled"},
        )
    finally:
        set_scheduler_engine(None)


async def test_run_scheduled_job_no_engine(caplog: object) -> None:
    """Handler should log error and return if no engine is set."""
    set_scheduler_engine(None)
    # Should not raise
    await run_scheduled_job(
        schedule_id="agent:daily",
        agent_id="agent",
        message="hello",
        input={},
    )
