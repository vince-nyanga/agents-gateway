"""Null queue implementation — used when no queue backend is configured."""

from __future__ import annotations

from agent_gateway.queue.models import ExecutionJob


class NullQueue:
    """No-op queue that rejects all operations.

    Used as the default when async execution is not configured.
    Calling enqueue raises RuntimeError to make misconfiguration obvious.
    """

    async def initialize(self) -> None:
        pass

    async def dispose(self) -> None:
        pass

    async def enqueue(self, job: ExecutionJob) -> None:
        raise RuntimeError(
            "No queue backend configured. Use gw.use_memory_queue(), "
            "gw.use_redis_queue(), or gw.use_rabbitmq_queue() to enable async execution."
        )

    async def dequeue(self, timeout: float = 0) -> ExecutionJob | None:  # noqa: ASYNC109
        return None

    async def ack(self, job_id: str) -> None:
        pass

    async def nack(self, job_id: str) -> None:
        pass

    async def request_cancel(self, job_id: str) -> bool:
        return False

    async def is_cancelled(self, job_id: str) -> bool:
        return False

    async def length(self) -> int:
        return 0
