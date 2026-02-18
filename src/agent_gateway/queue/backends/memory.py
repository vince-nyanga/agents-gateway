"""In-process asyncio.Queue backend — development and testing only.

Limitations:
- Jobs are lost on server restart (no persistence).
- Single-process only — cannot be shared across workers.
- ``--worker-only`` mode is not supported with this backend.
"""

from __future__ import annotations

import asyncio

from agent_gateway.queue.models import ExecutionJob


class MemoryQueue:
    """Wraps ``asyncio.Queue`` to implement the ``ExecutionQueue`` protocol."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ExecutionJob] = asyncio.Queue()
        self._cancelled: set[str] = set()

    async def initialize(self) -> None:
        pass

    async def dispose(self) -> None:
        self._cancelled.clear()

    async def enqueue(self, job: ExecutionJob) -> None:
        await self._queue.put(job)

    async def dequeue(self, timeout: float = 0) -> ExecutionJob | None:  # noqa: ASYNC109
        try:
            if timeout <= 0:
                return self._queue.get_nowait()
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except (asyncio.QueueEmpty, TimeoutError):
            return None

    async def ack(self, job_id: str) -> None:
        self._cancelled.discard(job_id)

    async def nack(self, job_id: str) -> None:
        # For memory backend, we cannot re-enqueue without the original job.
        # The worker must handle retry logic by re-enqueuing explicitly.
        pass

    async def request_cancel(self, job_id: str) -> bool:
        self._cancelled.add(job_id)
        return True

    async def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    async def length(self) -> int:
        return self._queue.qsize()
