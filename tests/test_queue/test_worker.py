"""Tests for the WorkerPool."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agent_gateway.config import QueueConfig
from agent_gateway.engine.models import (
    ExecutionResult,
    ExecutionStatus,
    StopReason,
    UsageAccumulator,
)
from agent_gateway.queue.backends.memory import MemoryQueue
from agent_gateway.queue.models import ExecutionJob
from agent_gateway.queue.worker import WorkerPool


def _make_job(execution_id: str = "exec-1") -> ExecutionJob:
    return ExecutionJob(
        execution_id=execution_id,
        agent_id="assistant",
        message="Hello",
        enqueued_at="2026-02-18T10:00:00+00:00",
    )


def _make_config(**overrides: Any) -> QueueConfig:
    defaults = {"workers": 1, "drain_timeout_s": 2, "max_retries": 3}
    defaults.update(overrides)
    return QueueConfig(**defaults)


def _make_mock_gateway(queue: MemoryQueue) -> MagicMock:
    """Build a mock Gateway with enough structure for the worker pool."""
    gw = MagicMock()
    gw._queue = queue
    gw._execution_semaphore = asyncio.Semaphore(4)
    gw._execution_handles = {}

    # Mock execution repo
    gw._execution_repo = AsyncMock()
    gw._execution_repo.update_status = AsyncMock()
    gw._execution_repo.update_result = AsyncMock()

    # Mock engine result
    result = ExecutionResult(
        output="Done",
        raw_text="Done",
        stop_reason=StopReason.COMPLETED,
        usage=UsageAccumulator(),
    )

    # Mock snapshot with engine and workspace
    mock_agent = MagicMock()
    mock_agent.id = "assistant"
    mock_workspace = MagicMock()
    mock_workspace.agents = {"assistant": mock_agent}

    mock_engine = AsyncMock()
    mock_engine.execute = AsyncMock(return_value=result)

    mock_snapshot = MagicMock()
    mock_snapshot.workspace = mock_workspace
    mock_snapshot.engine = mock_engine
    gw._snapshot = mock_snapshot

    return gw


async def test_worker_processes_job() -> None:
    """Worker dequeues and processes a job end-to-end."""
    queue = MemoryQueue()
    config = _make_config()
    gw = _make_mock_gateway(queue)
    pool = WorkerPool(queue=queue, gateway=gw, config=config)

    # Enqueue a job
    job = _make_job()
    await queue.enqueue(job)

    # Start workers, let them process
    await pool.start()
    await asyncio.sleep(0.2)  # Give worker time to process
    await pool.drain()

    # Verify execution happened
    gw._execution_repo.update_status.assert_any_call("exec-1", ExecutionStatus.RUNNING)
    gw._snapshot.engine.execute.assert_called_once()

    # Verify result was persisted
    gw._execution_repo.update_result.assert_called_once()


async def test_worker_skips_cancelled_job() -> None:
    """Worker skips jobs that were cancelled before dequeue."""
    queue = MemoryQueue()
    config = _make_config()
    gw = _make_mock_gateway(queue)
    pool = WorkerPool(queue=queue, gateway=gw, config=config)

    # Enqueue and cancel
    job = _make_job()
    await queue.enqueue(job)
    await queue.request_cancel("exec-1")

    await pool.start()
    await asyncio.sleep(0.2)
    await pool.drain()

    # Engine should NOT have been called
    gw._snapshot.engine.execute.assert_not_called()

    # Status should be CANCELLED
    gw._execution_repo.update_status.assert_called_with("exec-1", ExecutionStatus.CANCELLED)


async def test_worker_skips_max_retries_exceeded() -> None:
    """Worker skips jobs that exceed max_retries."""
    queue = MemoryQueue()
    config = _make_config(max_retries=2)
    gw = _make_mock_gateway(queue)
    pool = WorkerPool(queue=queue, gateway=gw, config=config)

    # Job with retry_count > max_retries
    job = ExecutionJob(
        execution_id="exec-1",
        agent_id="assistant",
        message="Hello",
        retry_count=3,
    )
    await queue.enqueue(job)

    await pool.start()
    await asyncio.sleep(0.2)
    await pool.drain()

    gw._snapshot.engine.execute.assert_not_called()
    gw._execution_repo.update_status.assert_called_with(
        "exec-1", ExecutionStatus.FAILED, error="max retries exceeded"
    )


async def test_worker_handles_missing_agent() -> None:
    """Worker handles a job for an agent that doesn't exist."""
    queue = MemoryQueue()
    config = _make_config()
    gw = _make_mock_gateway(queue)

    # Agent not in workspace
    gw._snapshot.workspace.agents = {}

    pool = WorkerPool(queue=queue, gateway=gw, config=config)

    await queue.enqueue(_make_job())
    await pool.start()
    await asyncio.sleep(0.2)
    await pool.drain()

    gw._snapshot.engine.execute.assert_not_called()
    gw._execution_repo.update_status.assert_any_call(
        "exec-1",
        ExecutionStatus.FAILED,
        error="Agent 'assistant' not found",
    )


async def test_drain_stops_workers() -> None:
    """Drain signals workers to stop and waits."""
    queue = MemoryQueue()
    config = _make_config()
    gw = _make_mock_gateway(queue)
    pool = WorkerPool(queue=queue, gateway=gw, config=config)

    await pool.start()
    assert len(pool._tasks) == 1

    await pool.drain()
    assert len(pool._tasks) == 0
