"""Module-level job handler for APScheduler.

APScheduler 3.x with SQLAlchemyJobStore serializes job references via pickle.
The callable must be importable by its fully-qualified module path. This module
provides a stable entry point that APScheduler can resolve on restart.

The gateway reference is set by SchedulerEngine.start() before any jobs fire.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_gateway.scheduler.engine import SchedulerEngine

logger = logging.getLogger(__name__)

# Module-level reference, set by SchedulerEngine.start()
_scheduler_engine: SchedulerEngine | None = None


def set_scheduler_engine(engine: SchedulerEngine | None) -> None:
    """Set the active scheduler engine reference. Called during startup/shutdown."""
    global _scheduler_engine  # noqa: PLW0603
    _scheduler_engine = engine


async def run_scheduled_job(
    schedule_id: str,
    agent_id: str,
    message: str,
    context: dict[str, Any],
) -> None:
    """Entry point called by APScheduler when a cron trigger fires.

    Dispatches to the SchedulerEngine which handles overlap prevention,
    execution dispatch, and state tracking.
    """
    if _scheduler_engine is None:
        logger.error("Scheduled job fired but no scheduler engine is active")
        return

    await _scheduler_engine.dispatch_scheduled_execution(
        schedule_id=schedule_id,
        agent_id=agent_id,
        message=message,
        context=context,
    )
