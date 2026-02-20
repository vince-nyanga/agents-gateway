"""Notification worker — consumes jobs from the notification queue."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from agent_gateway.notifications.models import (
    AgentNotificationConfig,
    NotificationJob,
    build_notification_event,
)

if TYPE_CHECKING:
    from agent_gateway.notifications.engine import NotificationEngine

logger = logging.getLogger(__name__)

# Type alias for any notification queue backend
NotificationQueue = Any


class NotificationWorker:
    """Single consumer coroutine that dequeues and delivers notification jobs."""

    def __init__(
        self,
        queue: NotificationQueue,
        engine: NotificationEngine,
    ) -> None:
        self._queue = queue
        self._engine = engine
        self._task: asyncio.Task[None] | None = None
        self._shutting_down = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._worker_loop(), name="notification-worker")
        logger.info("Notification worker started")

    async def drain(self) -> None:
        self._shutting_down = True
        if self._task is not None:
            # Give it a few seconds to finish current job
            done, pending = await asyncio.wait([self._task], timeout=10.0)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._task = None
        logger.info("Notification worker drained")

    async def _worker_loop(self) -> None:
        while not self._shutting_down:
            try:
                job = await self._queue.dequeue(timeout=1.0)
            except Exception:
                logger.warning("Notification worker: dequeue failed", exc_info=True)
                await asyncio.sleep(1.0)
                continue

            if job is None:
                continue

            await self._process_job(job)

    async def _process_job(self, job: NotificationJob) -> None:
        try:
            event = build_notification_event(
                execution_id=job.execution_id,
                agent_id=job.agent_id,
                status=job.status,
                message=job.message,
                result=job.result,
                error=job.error,
                usage=job.usage,
                duration_ms=job.duration_ms,
                input=job.input,
            )
            config = AgentNotificationConfig.from_dict(job.config)

            await self._engine.notify(event, config)
            await self._queue.ack(job.job_id)
        except Exception:
            logger.warning(
                "Notification worker: job %s failed, nacking",
                job.job_id,
                exc_info=True,
            )
            await self._queue.nack(job.job_id)
