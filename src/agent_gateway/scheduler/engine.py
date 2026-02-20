"""Scheduler engine — manages cron-based agent invocations via APScheduler 3.x."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from agent_gateway.persistence.domain import ScheduleRecord
from agent_gateway.scheduler.handler import run_scheduled_job, set_scheduler_engine

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from agent_gateway.config import SchedulerConfig
    from agent_gateway.persistence.protocols import ExecutionRepository, ScheduleRepository
    from agent_gateway.queue.protocol import ExecutionQueue
    from agent_gateway.workspace.agent import AgentDefinition, ScheduleConfig

logger = logging.getLogger(__name__)


class SchedulerEngine:
    """Manages cron-based agent scheduling via APScheduler 3.x AsyncIOScheduler.

    Wraps APScheduler behind a thin interface so it can be swapped
    to v4 when it stabilizes.
    """

    def __init__(
        self,
        config: SchedulerConfig,
        schedule_repo: ScheduleRepository,
        execution_repo: ExecutionRepository,
        queue: ExecutionQueue,
        invoke_fn: Callable[..., Coroutine[Any, Any, Any]],
        track_task: Callable[[asyncio.Task[None]], None],
        timezone: str = "UTC",
    ) -> None:
        self._config = config
        self._schedule_repo = schedule_repo
        self._execution_repo = execution_repo
        self._queue = queue
        self._invoke_fn = invoke_fn
        self._track_task = track_task
        self._timezone = timezone

        # APScheduler instance, created in start()
        self._scheduler: AsyncIOScheduler | None = None

        # Overlap prevention: tracks schedule_ids with monotonic fire time
        self._active_scheduled: dict[str, float] = {}
        self._active_lock = asyncio.Lock()

        # Schedule definitions keyed by schedule_id for lookup at fire time
        self._schedule_configs: dict[str, ScheduleConfig] = {}
        self._agent_map: dict[str, str] = {}  # schedule_id -> agent_id

    async def start(
        self,
        schedules: list[ScheduleConfig],
        agents: dict[str, AgentDefinition],
    ) -> None:
        """Register schedules and start the APScheduler background loop."""
        # Build schedule_id -> config mapping
        for agent in agents.values():
            for sched in agent.schedules:
                schedule_id = f"{agent.id}:{sched.name}"
                self._schedule_configs[schedule_id] = sched
                self._agent_map[schedule_id] = agent.id

        # Configure APScheduler with in-memory job store.
        # SQLAlchemyJobStore is intentionally avoided because APScheduler 3.x
        # uses pickle serialization which is an RCE risk.
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            timezone=self._timezone,
        )

        # Set the module-level reference so the handler can reach us
        set_scheduler_engine(self)

        # Register each schedule as a cron job
        for schedule_id, sched_config in self._schedule_configs.items():
            agent_id = self._agent_map[schedule_id]
            await self._register_job(schedule_id, agent_id, sched_config)

        self._scheduler.start()

        # Sync to persistence (after start so next_run_time is computed)
        await self._sync_schedule_records(agents)
        enabled_count = sum(1 for s in schedules if s.enabled)
        logger.info(
            "Scheduler started: %d schedules (%d enabled)",
            len(schedules),
            enabled_count,
        )

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

        set_scheduler_engine(None)
        logger.info("Scheduler stopped")

    async def _register_job(
        self,
        schedule_id: str,
        agent_id: str,
        sched_config: ScheduleConfig,
    ) -> None:
        """Register a single cron job with APScheduler."""
        if self._scheduler is None:
            return

        # Per-schedule timezone takes priority; fall back to gateway default
        tz = sched_config.timezone or self._timezone

        trigger = CronTrigger.from_crontab(sched_config.cron, timezone=tz)

        context = dict(sched_config.context) if sched_config.context else {}
        context["source"] = "scheduled"
        context["schedule_id"] = schedule_id
        context["schedule_name"] = sched_config.name

        self._scheduler.add_job(
            run_scheduled_job,
            trigger=trigger,
            id=schedule_id,
            name=f"schedule:{schedule_id}",
            kwargs={
                "schedule_id": schedule_id,
                "agent_id": agent_id,
                "message": sched_config.message,
                "context": context,
            },
            replace_existing=True,
            coalesce=self._config.coalesce,
            misfire_grace_time=self._config.misfire_grace_seconds,
            max_instances=self._config.max_instances,
        )

        # Pause if disabled
        if not sched_config.enabled:
            self._scheduler.pause_job(schedule_id)

    async def _sync_schedule_records(
        self,
        agents: dict[str, AgentDefinition],
    ) -> None:
        """Sync workspace schedule configs to persistence ScheduleRecords."""
        for agent in agents.values():
            for sched in agent.schedules:
                schedule_id = f"{agent.id}:{sched.name}"
                next_run = self._get_next_run_time(schedule_id)

                record = ScheduleRecord(
                    id=schedule_id,
                    agent_id=agent.id,
                    name=sched.name,
                    cron_expr=sched.cron,
                    message=sched.message,
                    context=dict(sched.context) if sched.context else None,
                    enabled=sched.enabled,
                    timezone=sched.timezone or self._timezone,
                    next_run_at=next_run,
                    created_at=datetime.now(UTC),
                )
                await self._schedule_repo.upsert(record)

    def _get_next_run_time(self, schedule_id: str) -> datetime | None:
        """Get the next fire time for a schedule from APScheduler."""
        if self._scheduler is None:
            return None
        job = self._scheduler.get_job(schedule_id)
        if job is None:
            return None
        next_time: datetime | None = job.next_run_time
        return next_time

    async def dispatch_scheduled_execution(
        self,
        schedule_id: str,
        agent_id: str,
        message: str,
        context: dict[str, Any],
    ) -> None:
        """Dispatch a scheduled agent execution. Called by the handler module."""
        # Overlap check with safety valve: auto-clear after 2x misfire grace
        timeout = self._config.misfire_grace_seconds * 2
        async with self._active_lock:
            fire_time = self._active_scheduled.get(schedule_id)
            if fire_time is not None:
                elapsed = time.monotonic() - fire_time
                if elapsed < timeout:
                    logger.warning(
                        "Schedule '%s' still running (%.0fs), skipping overlapping fire",
                        schedule_id,
                        elapsed,
                    )
                    return
                logger.warning(
                    "Schedule '%s' stuck for %.0fs (timeout=%ds), force-clearing",
                    schedule_id,
                    elapsed,
                    timeout,
                )
            self._active_scheduled[schedule_id] = time.monotonic()

        try:
            await self._do_dispatch(schedule_id, agent_id, message, context)
        except Exception:
            logger.exception("Scheduled execution for '%s' failed", schedule_id)
            async with self._active_lock:
                self._active_scheduled.pop(schedule_id, None)
            # Update last_run_at even on failure
            await self._update_after_run(schedule_id)

    async def _do_dispatch(
        self,
        schedule_id: str,
        agent_id: str,
        message: str,
        context: dict[str, Any],
    ) -> None:
        """Internal dispatch — either enqueue to worker pool or invoke directly."""
        from agent_gateway.persistence.domain import ExecutionRecord
        from agent_gateway.queue.null import NullQueue

        execution_id = str(uuid.uuid4())

        record = ExecutionRecord(
            id=execution_id,
            agent_id=agent_id,
            status="queued",
            message=message,
            context=context,
            schedule_id=schedule_id,
            schedule_name=context.get("schedule_name", ""),
            created_at=datetime.now(UTC),
        )
        await self._execution_repo.create(record)

        if not isinstance(self._queue, NullQueue):
            from agent_gateway.queue.models import ExecutionJob

            job = ExecutionJob(
                execution_id=execution_id,
                agent_id=agent_id,
                message=message,
                context=context,
                enqueued_at=datetime.now(UTC).isoformat(),
                schedule_id=schedule_id,
            )
            await self._queue.enqueue(job)
            logger.info(
                "Scheduled execution '%s' enqueued: agent=%s, execution=%s",
                schedule_id,
                agent_id,
                execution_id,
            )
        else:
            try:
                await self._invoke_fn(agent_id, message, context=context)
            finally:
                async with self._active_lock:
                    self._active_scheduled.pop(schedule_id, None)
                await self._update_after_run(schedule_id)

    async def on_execution_complete(self, schedule_id: str) -> None:
        """Called by the worker pool when a scheduled execution finishes.

        Removes the schedule from the active set and updates last_run_at.
        """
        async with self._active_lock:
            self._active_scheduled.pop(schedule_id, None)
        await self._update_after_run(schedule_id)

    async def _update_after_run(self, schedule_id: str) -> None:
        """Update the schedule's last_run_at and next_run_at in persistence."""
        next_run = self._get_next_run_time(schedule_id)
        await self._schedule_repo.update_last_run(
            schedule_id=schedule_id,
            last_run_at=datetime.now(UTC),
            next_run_at=next_run,
        )

    # --- Public API for schedule management (used by API routes) ---

    async def pause(self, schedule_id: str) -> bool:
        """Pause a schedule. Returns True if the schedule was found."""
        if self._scheduler is None:
            return False
        job = self._scheduler.get_job(schedule_id)
        if job is None:
            return False
        self._scheduler.pause_job(schedule_id)
        await self._schedule_repo.update_enabled(schedule_id, False)
        return True

    async def resume(self, schedule_id: str) -> bool:
        """Resume a paused schedule. Returns True if the schedule was found."""
        if self._scheduler is None:
            return False
        job = self._scheduler.get_job(schedule_id)
        if job is None:
            return False
        self._scheduler.resume_job(schedule_id)
        await self._schedule_repo.update_enabled(schedule_id, True)
        # Update next_run_at after resume (don't touch last_run_at)
        next_run = self._get_next_run_time(schedule_id)
        if next_run:
            await self._schedule_repo.update_next_run(schedule_id, next_run)
        return True

    async def trigger(self, schedule_id: str) -> str | None:
        """Manually trigger a scheduled job. Returns execution_id or None."""
        config = self._schedule_configs.get(schedule_id)
        agent_id = self._agent_map.get(schedule_id)
        if config is None or agent_id is None:
            return None

        execution_id = str(uuid.uuid4())
        context: dict[str, Any] = dict(config.context) if config.context else {}
        context["source"] = "manual_trigger"
        context["schedule_id"] = schedule_id
        context["schedule_name"] = config.name

        from agent_gateway.persistence.domain import ExecutionRecord

        record = ExecutionRecord(
            id=execution_id,
            agent_id=agent_id,
            status="queued",
            message=config.message,
            context=context,
            schedule_id=schedule_id,
            schedule_name=config.name,
            created_at=datetime.now(UTC),
        )
        await self._execution_repo.create(record)

        # Dispatch via gateway invoke (direct, not queued)
        task = asyncio.create_task(
            self._run_manual_trigger(execution_id, agent_id, config.message, context),
            name=f"manual-trigger-{execution_id}",
        )
        self._track_task(task)
        return execution_id

    async def _run_manual_trigger(
        self,
        execution_id: str,
        agent_id: str,
        message: str,
        context: dict[str, Any],
    ) -> None:
        """Run a manually triggered schedule execution in the background."""
        try:
            result = await self._invoke_fn(agent_id, message, context=context)
            await self._execution_repo.update_status(
                execution_id,
                "completed",
                completed_at=datetime.now(UTC),
            )
            await self._execution_repo.update_result(
                execution_id,
                result=result.to_dict(),
                usage=result.usage.to_dict(),
            )
        except Exception as exc:
            logger.exception("Manual trigger execution %s failed", execution_id)
            await self._execution_repo.update_status(
                execution_id,
                "failed",
                error=str(exc),
            )

    async def get_schedules(self) -> list[dict[str, Any]]:
        """List all schedules with live next_run_at from APScheduler."""
        records = await self._schedule_repo.list_all()
        result = []
        for rec in records:
            # Get live next_run_at from APScheduler if available
            next_run = self._get_next_run_time(rec.id) or rec.next_run_at
            result.append(
                {
                    "id": rec.id,
                    "agent_id": rec.agent_id,
                    "name": rec.name,
                    "cron_expr": rec.cron_expr,
                    "enabled": rec.enabled,
                    "timezone": rec.timezone,
                    "next_run_at": next_run,
                    "last_run_at": rec.last_run_at,
                    "created_at": rec.created_at,
                }
            )
        return result

    async def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        """Get a single schedule with full details."""
        rec = await self._schedule_repo.get(schedule_id)
        if rec is None or rec.deleted_at is not None:
            return None

        next_run = self._get_next_run_time(schedule_id) or rec.next_run_at
        return {
            "id": rec.id,
            "agent_id": rec.agent_id,
            "name": rec.name,
            "cron_expr": rec.cron_expr,
            "message": rec.message,
            "context": rec.context or {},
            "enabled": rec.enabled,
            "timezone": rec.timezone,
            "next_run_at": next_run,
            "last_run_at": rec.last_run_at,
            "created_at": rec.created_at,
        }
