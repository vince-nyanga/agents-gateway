"""ExecutionQueue protocol — structural typing for pluggable queue backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_gateway.queue.models import ExecutionJob


@runtime_checkable
class ExecutionQueue(Protocol):
    """Pluggable queue backend for async agent execution.

    Implementations must handle job lifecycle: enqueue → dequeue → ack/nack.
    Cancellation is cooperative: the caller writes intent via ``request_cancel``,
    and the worker checks via ``is_cancelled`` before each LLM iteration.
    """

    async def initialize(self) -> None:
        """Set up connections, create consumer groups, etc."""
        ...

    async def dispose(self) -> None:
        """Release connections and resources."""
        ...

    async def enqueue(self, job: ExecutionJob) -> None:
        """Add a job to the queue."""
        ...

    async def dequeue(self, timeout: float = 0) -> ExecutionJob | None:  # noqa: ASYNC109
        """Fetch the next job, or None if the queue is empty / timeout expires.

        Args:
            timeout: Max seconds to wait for a job. 0 means non-blocking.
        """
        ...

    async def ack(self, job_id: str) -> None:
        """Acknowledge successful processing of a job.

        After ack, the job will not be re-delivered.
        """
        ...

    async def nack(self, job_id: str) -> None:
        """Negative-acknowledge a job, requesting re-delivery.

        Memory: re-enqueues immediately.
        Redis: no-op (PEL handles re-delivery after visibility timeout).
        RabbitMQ: basic_nack with requeue=True.
        """
        ...

    async def request_cancel(self, job_id: str) -> bool:
        """Signal that a job should be cancelled.

        Returns True if the cancel signal was recorded. The worker checks
        ``is_cancelled`` before each LLM iteration.
        """
        ...

    async def is_cancelled(self, job_id: str) -> bool:
        """Check whether cancellation has been requested for a job."""
        ...

    async def length(self) -> int:
        """Return the approximate number of pending jobs in the queue."""
        ...
