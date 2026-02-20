"""RabbitMQ queue integration tests using testcontainers.

Requires Docker to be running. Skipped automatically when Docker is unavailable.
Run with: uv run pytest -m rabbitmq
"""

from __future__ import annotations

import os

import pytest

from agent_gateway.queue.backends.rabbitmq import RabbitMQQueue
from agent_gateway.queue.models import ExecutionJob

pytestmark = pytest.mark.rabbitmq


@pytest.fixture(scope="session")
def rabbitmq_container():
    """Session-scoped RabbitMQ container."""
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

    try:
        from testcontainers.rabbitmq import RabbitMqContainer

        container = RabbitMqContainer("rabbitmq:3-management")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")

    port = container.get_exposed_port(5672)
    url = f"amqp://guest:guest@localhost:{port}/"
    yield url
    container.stop()


@pytest.fixture
async def rabbitmq_queue(rabbitmq_container: str):
    """Function-scoped RabbitMQQueue with a unique queue per test."""
    import uuid

    queue_name = f"ag.test.{uuid.uuid4().hex[:8]}"
    queue = RabbitMQQueue(url=rabbitmq_container, queue_name=queue_name)
    await queue.initialize()
    yield queue
    await queue.dispose()


def _make_job(execution_id: str = "exec-1") -> ExecutionJob:
    return ExecutionJob(
        execution_id=execution_id,
        agent_id="agent-a",
        message="Hello",
        input={"key": "value"},
        enqueued_at="2026-02-18T10:00:00+00:00",
    )


async def test_enqueue_dequeue_round_trip(rabbitmq_queue: RabbitMQQueue) -> None:
    """Enqueue then dequeue returns the same job."""
    job = _make_job()
    await rabbitmq_queue.enqueue(job)

    result = await rabbitmq_queue.dequeue(timeout=2.0)
    assert result is not None
    assert result.execution_id == "exec-1"
    assert result.agent_id == "agent-a"
    assert result.message == "Hello"


async def test_dequeue_empty_returns_none(rabbitmq_queue: RabbitMQQueue) -> None:
    """Dequeue on empty queue returns None."""
    result = await rabbitmq_queue.dequeue(timeout=0.5)
    assert result is None


async def test_ack_removes_message(rabbitmq_queue: RabbitMQQueue) -> None:
    """Ack removes the message from the queue."""
    await rabbitmq_queue.enqueue(_make_job())
    job = await rabbitmq_queue.dequeue(timeout=2.0)
    assert job is not None

    await rabbitmq_queue.ack(job.execution_id)

    # Queue should be empty now
    result = await rabbitmq_queue.dequeue(timeout=0.5)
    assert result is None


async def test_cancel_signal(rabbitmq_queue: RabbitMQQueue) -> None:
    """Cancel signal is received by the same consumer."""
    assert not await rabbitmq_queue.is_cancelled("exec-1")

    result = await rabbitmq_queue.request_cancel("exec-1")
    assert result is True

    # Give time for the fanout message to arrive
    import asyncio

    await asyncio.sleep(0.2)
    assert await rabbitmq_queue.is_cancelled("exec-1")


async def test_multiple_jobs_fifo(rabbitmq_queue: RabbitMQQueue) -> None:
    """Jobs are delivered in order."""
    await rabbitmq_queue.enqueue(_make_job("first"))
    await rabbitmq_queue.enqueue(_make_job("second"))
    await rabbitmq_queue.enqueue(_make_job("third"))

    r1 = await rabbitmq_queue.dequeue(timeout=2.0)
    r2 = await rabbitmq_queue.dequeue(timeout=2.0)
    r3 = await rabbitmq_queue.dequeue(timeout=2.0)

    assert r1 is not None and r1.execution_id == "first"
    assert r2 is not None and r2.execution_id == "second"
    assert r3 is not None and r3.execution_id == "third"
