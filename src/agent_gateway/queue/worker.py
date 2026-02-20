"""Worker pool — consumes jobs from the execution queue."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionStatus,
    StopReason,
)
from agent_gateway.queue.models import ExecutionJob
from agent_gateway.telemetry.metrics import create_metrics
from agent_gateway.telemetry.tracing import queue_process_span, set_span_error, set_span_ok
from agent_gateway.tools.runner import execute_tool

if TYPE_CHECKING:
    from agent_gateway.config import QueueConfig
    from agent_gateway.gateway import Gateway
    from agent_gateway.queue.protocol import ExecutionQueue

logger = logging.getLogger(__name__)


def _stop_reason_to_status(reason: StopReason) -> ExecutionStatus:
    """Map a StopReason to the corresponding ExecutionStatus."""
    mapping = {
        StopReason.COMPLETED: ExecutionStatus.COMPLETED,
        StopReason.CANCELLED: ExecutionStatus.CANCELLED,
        StopReason.TIMEOUT: ExecutionStatus.TIMEOUT,
        StopReason.ERROR: ExecutionStatus.FAILED,
        StopReason.MAX_ITERATIONS: ExecutionStatus.COMPLETED,
        StopReason.MAX_TOOL_CALLS: ExecutionStatus.COMPLETED,
    }
    return mapping.get(reason, ExecutionStatus.FAILED)


class WorkerPool:
    """Manages N worker coroutines consuming from the execution queue."""

    def __init__(
        self,
        queue: ExecutionQueue,
        gateway: Gateway,
        config: QueueConfig,
    ) -> None:
        self._queue = queue
        self._gateway = gateway
        self._config = config
        self._metrics = create_metrics()
        self._tasks: list[asyncio.Task[None]] = []
        self._shutting_down = False

    async def start(self) -> None:
        """Start worker coroutines."""
        num_workers = self._config.workers
        for i in range(num_workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"queue-worker-{i}")
            self._tasks.append(task)

        logger.info("Worker pool started: %d workers", num_workers)

    async def drain(self) -> None:
        """Stop accepting new jobs and wait for in-flight work to finish."""
        self._shutting_down = True
        drain_timeout = self._config.drain_timeout_s

        if self._tasks:
            # Wait for workers to finish current jobs, then cancel
            done, pending = await asyncio.wait(self._tasks, timeout=drain_timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        self._tasks.clear()
        logger.info("Worker pool drained")

    async def _worker_loop(self, worker_id: int) -> None:
        """Main loop for a single worker coroutine."""
        gw = self._gateway

        while not self._shutting_down:
            try:
                job = await self._queue.dequeue(timeout=1.0)
            except Exception:
                logger.warning("Worker %d: dequeue failed", worker_id, exc_info=True)
                await asyncio.sleep(1.0)
                continue

            if job is None:
                continue

            # Check cancel BEFORE execution
            if await self._queue.is_cancelled(job.execution_id):
                await self._queue.ack(job.execution_id)
                await gw._execution_repo.update_status(job.execution_id, ExecutionStatus.CANCELLED)
                logger.info(
                    "Worker %d: job %s cancelled before execution",
                    worker_id,
                    job.execution_id,
                )
                continue

            # Check max_retries
            if job.retry_count > self._config.max_retries:
                await self._queue.ack(job.execution_id)
                await gw._execution_repo.update_status(
                    job.execution_id,
                    ExecutionStatus.FAILED,
                    error="max retries exceeded",
                )
                logger.warning(
                    "Worker %d: job %s exceeded max retries (%d)",
                    worker_id,
                    job.execution_id,
                    self._config.max_retries,
                )
                continue

            await self._process_job(worker_id, job)

    async def _process_job(self, worker_id: int, job: ExecutionJob) -> None:
        """Execute a single job with error handling and ack/nack."""
        gw = self._gateway
        semaphore = gw._execution_semaphore
        attrs = {"agent_id": job.agent_id, "worker_id": str(worker_id)}

        if semaphore is None:
            logger.error("Worker %d: execution semaphore not initialized", worker_id)
            self._metrics.queue_jobs_failed.add(1, attrs)
            await self._queue.nack(job.execution_id)
            return

        notify_args: dict[str, Any] | None = None
        start = time.monotonic()
        with queue_process_span(job.execution_id, job.agent_id, worker_id) as span:
            try:
                async with semaphore:
                    notify_args = await self._run_execution(worker_id, job)
                await self._queue.ack(job.execution_id)

                duration_ms = int((time.monotonic() - start) * 1000)
                self._metrics.queue_jobs_completed.add(1, attrs)
                self._metrics.queue_job_duration.record(duration_ms, attrs)
                self._metrics.queue_depth.add(-1, {"agent_id": job.agent_id})
                set_span_ok(span)
            except Exception as exc:
                logger.error(
                    "Worker %d: job %s failed unexpectedly",
                    worker_id,
                    job.execution_id,
                    exc_info=True,
                )
                self._metrics.queue_jobs_failed.add(1, attrs)
                set_span_error(span, exc)
                await self._queue.nack(job.execution_id)

        # Fire notifications via the consolidated gateway helper
        if notify_args is not None:
            gw.fire_notifications(**notify_args)

        # Notify scheduler that a scheduled execution completed
        if job.schedule_id:
            scheduler = gw._scheduler
            if scheduler is not None:
                await scheduler.on_execution_complete(job.schedule_id)

    async def _run_execution(self, worker_id: int, job: ExecutionJob) -> dict[str, Any] | None:
        """Run the agent execution for a job.

        Returns notification keyword arguments to be fired *after* the
        semaphore is released, or ``None`` if no notification is needed.
        """
        gw = self._gateway
        snapshot = gw._snapshot
        if snapshot is None or snapshot.engine is None:
            raise RuntimeError("Gateway not initialized")

        agent = snapshot.workspace.agents.get(job.agent_id)
        if agent is None:
            await gw._execution_repo.update_status(
                job.execution_id,
                ExecutionStatus.FAILED,
                error=f"Agent '{job.agent_id}' not found",
            )
            return None

        # Update status to running
        await gw._execution_repo.update_status(job.execution_id, ExecutionStatus.RUNNING)

        # Create handle for cooperative cancellation
        handle = ExecutionHandle(job.execution_id)
        gw._execution_handles[job.execution_id] = handle

        exec_options = ExecutionOptions(
            timeout_ms=job.timeout_ms,
            output_schema=job.output_schema,
        )

        start = time.monotonic()
        try:
            # Check cancel periodically via the queue
            # The handle is checked inside the engine loop; we also wire
            # queue-based cancel into the handle.
            cancel_task = asyncio.create_task(
                self._poll_cancel(job.execution_id, handle),
                name=f"cancel-poll-{job.execution_id}",
            )

            try:
                result = await snapshot.engine.execute(
                    agent=agent,
                    message=job.message,
                    workspace=snapshot.workspace,
                    input=job.input,
                    options=exec_options,
                    handle=handle,
                    tool_executor=execute_tool,
                )
            finally:
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task

            duration_ms = int((time.monotonic() - start) * 1000)
            status = _stop_reason_to_status(result.stop_reason)

            await gw._execution_repo.update_status(
                job.execution_id, status, completed_at=datetime.now(UTC)
            )
            await gw._execution_repo.update_result(
                job.execution_id,
                result=result.to_dict(),
                usage=result.usage.to_dict(),
            )

            logger.info(
                "Worker %d: job %s completed (%s, %dms)",
                worker_id,
                job.execution_id,
                status,
                duration_ms,
            )

            return {
                "execution_id": job.execution_id,
                "agent_id": agent.id,
                "status": status.value,
                "message": job.message,
                "config": agent.notifications,
                "result": result.to_dict() if result.raw_text else None,
                "usage": result.usage.to_dict() if result.usage else None,
                "input": job.input,
                "duration_ms": duration_ms,
            }
        except Exception as e:
            logger.error(
                "Worker %d: job %s execution failed: %s",
                worker_id,
                job.execution_id,
                e,
            )
            await gw._execution_repo.update_status(
                job.execution_id, ExecutionStatus.FAILED, error=str(e)
            )

            return {
                "execution_id": job.execution_id,
                "agent_id": agent.id,
                "status": "failed",
                "message": job.message,
                "config": agent.notifications,
                "error": str(e),
                "input": job.input,
            }
        finally:
            gw._execution_handles.pop(job.execution_id, None)

    async def _poll_cancel(self, execution_id: str, handle: ExecutionHandle) -> None:
        """Periodically check the queue for cancel signals and relay to the handle."""
        try:
            while not handle.is_cancelled:
                await asyncio.sleep(1.0)
                if await self._queue.is_cancelled(execution_id):
                    handle.cancel()
                    break
        except asyncio.CancelledError:
            pass
