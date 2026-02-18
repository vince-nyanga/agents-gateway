"""Tests for the MemoryQueue backend."""

from __future__ import annotations

import pytest

from agent_gateway.queue.backends.memory import MemoryQueue
from agent_gateway.queue.models import ExecutionJob


@pytest.fixture
def queue() -> MemoryQueue:
    return MemoryQueue()


def _make_job(execution_id: str = "exec-1") -> ExecutionJob:
    return ExecutionJob(
        execution_id=execution_id,
        agent_id="agent-a",
        message="Hello",
        enqueued_at="2026-02-18T10:00:00+00:00",
    )


async def test_enqueue_dequeue_round_trip(queue: MemoryQueue) -> None:
    """Enqueue then dequeue returns the same job."""
    job = _make_job()
    await queue.enqueue(job)

    result = await queue.dequeue(timeout=0)
    assert result is not None
    assert result.execution_id == "exec-1"
    assert result.agent_id == "agent-a"


async def test_dequeue_empty_returns_none(queue: MemoryQueue) -> None:
    """Dequeue on empty queue returns None."""
    result = await queue.dequeue(timeout=0)
    assert result is None


async def test_dequeue_timeout_returns_none(queue: MemoryQueue) -> None:
    """Dequeue with short timeout on empty queue returns None."""
    result = await queue.dequeue(timeout=0.05)
    assert result is None


async def test_fifo_ordering(queue: MemoryQueue) -> None:
    """Jobs dequeue in FIFO order."""
    await queue.enqueue(_make_job("first"))
    await queue.enqueue(_make_job("second"))
    await queue.enqueue(_make_job("third"))

    r1 = await queue.dequeue()
    r2 = await queue.dequeue()
    r3 = await queue.dequeue()

    assert r1 is not None and r1.execution_id == "first"
    assert r2 is not None and r2.execution_id == "second"
    assert r3 is not None and r3.execution_id == "third"


async def test_length(queue: MemoryQueue) -> None:
    """Length reflects the number of pending jobs."""
    assert await queue.length() == 0

    await queue.enqueue(_make_job("a"))
    await queue.enqueue(_make_job("b"))
    assert await queue.length() == 2

    await queue.dequeue()
    assert await queue.length() == 1


async def test_request_cancel_and_is_cancelled(queue: MemoryQueue) -> None:
    """Cancel tracking works for known IDs."""
    assert not await queue.is_cancelled("exec-1")

    result = await queue.request_cancel("exec-1")
    assert result is True
    assert await queue.is_cancelled("exec-1")


async def test_ack_clears_cancel(queue: MemoryQueue) -> None:
    """Ack clears the cancel flag for a job."""
    await queue.request_cancel("exec-1")
    assert await queue.is_cancelled("exec-1")

    await queue.ack("exec-1")
    assert not await queue.is_cancelled("exec-1")


async def test_cancel_before_dequeue(queue: MemoryQueue) -> None:
    """A job marked cancelled before dequeue is still dequeued but flagged."""
    job = _make_job()
    await queue.enqueue(job)
    await queue.request_cancel("exec-1")

    result = await queue.dequeue()
    assert result is not None
    assert await queue.is_cancelled(result.execution_id)


async def test_dispose_clears_state(queue: MemoryQueue) -> None:
    """Dispose clears all internal state."""
    await queue.request_cancel("exec-1")
    await queue.dispose()

    assert not await queue.is_cancelled("exec-1")
