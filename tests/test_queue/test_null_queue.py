"""Tests for the NullQueue."""

from __future__ import annotations

import pytest

from agent_gateway.queue.models import ExecutionJob
from agent_gateway.queue.null import NullQueue


async def test_null_queue_enqueue_raises() -> None:
    """Enqueue on NullQueue raises RuntimeError with helpful message."""
    q = NullQueue()
    job = ExecutionJob(execution_id="x", agent_id="a", message="m")

    with pytest.raises(RuntimeError, match="No queue backend configured"):
        await q.enqueue(job)


async def test_null_queue_dequeue_returns_none() -> None:
    """Dequeue on NullQueue always returns None."""
    q = NullQueue()
    assert await q.dequeue() is None


async def test_null_queue_cancel_returns_false() -> None:
    """Cancel on NullQueue returns False."""
    q = NullQueue()
    assert await q.request_cancel("x") is False
    assert await q.is_cancelled("x") is False


async def test_null_queue_length_is_zero() -> None:
    """Length on NullQueue is always 0."""
    q = NullQueue()
    assert await q.length() == 0
