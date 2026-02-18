"""Redis queue integration tests using testcontainers.

Requires Docker to be running. Skipped automatically when Docker is unavailable.
Run with: uv run pytest -m redis
"""

from __future__ import annotations

import os

import pytest

from agent_gateway.queue.backends.redis import RedisQueue
from agent_gateway.queue.models import ExecutionJob

pytestmark = pytest.mark.redis


@pytest.fixture(scope="session")
def redis_container():
    """Session-scoped Redis container — starts once, shared by all tests."""
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

    try:
        from testcontainers.redis import RedisContainer

        container = RedisContainer("redis:7")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")

    url = f"redis://localhost:{container.get_exposed_port(6379)}/0"
    yield url
    container.stop()


@pytest.fixture
async def redis_queue(redis_container: str):
    """Function-scoped RedisQueue with a unique stream per test."""
    import uuid

    stream_key = f"ag:test:{uuid.uuid4().hex[:8]}"
    group = f"test-group-{uuid.uuid4().hex[:8]}"

    queue = RedisQueue(
        url=redis_container,
        stream_key=stream_key,
        consumer_group=group,
    )
    await queue.initialize()
    yield queue
    await queue.dispose()


def _make_job(execution_id: str = "exec-1") -> ExecutionJob:
    return ExecutionJob(
        execution_id=execution_id,
        agent_id="agent-a",
        message="Hello",
        context={"key": "value"},
        enqueued_at="2026-02-18T10:00:00+00:00",
    )


async def test_enqueue_dequeue_round_trip(redis_queue: RedisQueue) -> None:
    """Enqueue then dequeue returns the same job."""
    job = _make_job()
    await redis_queue.enqueue(job)

    result = await redis_queue.dequeue(timeout=2.0)
    assert result is not None
    assert result.execution_id == "exec-1"
    assert result.agent_id == "agent-a"
    assert result.message == "Hello"
    assert result.context == {"key": "value"}


async def test_dequeue_empty_returns_none(redis_queue: RedisQueue) -> None:
    """Dequeue on empty stream returns None."""
    result = await redis_queue.dequeue(timeout=0.1)
    assert result is None


async def test_ack_removes_from_pending(redis_queue: RedisQueue) -> None:
    """Ack removes the job from the pending entry list."""
    await redis_queue.enqueue(_make_job())
    job = await redis_queue.dequeue(timeout=2.0)
    assert job is not None

    await redis_queue.ack(job.execution_id)

    # Verify no pending messages
    pending = await redis_queue._redis.xpending(
        redis_queue._stream_key, redis_queue._consumer_group
    )
    assert pending["pending"] == 0


async def test_cancel_via_redis_key(redis_queue: RedisQueue) -> None:
    """Cancel sets a Redis key, is_cancelled reads it."""
    assert not await redis_queue.is_cancelled("exec-1")

    result = await redis_queue.request_cancel("exec-1")
    assert result is True
    assert await redis_queue.is_cancelled("exec-1")


async def test_ack_clears_cancel_key(redis_queue: RedisQueue) -> None:
    """Ack clears the cancel key for a job."""
    await redis_queue.enqueue(_make_job())
    job = await redis_queue.dequeue(timeout=2.0)
    assert job is not None

    await redis_queue.request_cancel("exec-1")
    assert await redis_queue.is_cancelled("exec-1")

    await redis_queue.ack("exec-1")
    assert not await redis_queue.is_cancelled("exec-1")


async def test_length(redis_queue: RedisQueue) -> None:
    """Length reflects stream size."""
    assert await redis_queue.length() == 0

    await redis_queue.enqueue(_make_job("a"))
    await redis_queue.enqueue(_make_job("b"))
    assert await redis_queue.length() == 2


async def test_multiple_jobs_fifo(redis_queue: RedisQueue) -> None:
    """Jobs are delivered in FIFO order."""
    await redis_queue.enqueue(_make_job("first"))
    await redis_queue.enqueue(_make_job("second"))
    await redis_queue.enqueue(_make_job("third"))

    r1 = await redis_queue.dequeue(timeout=2.0)
    r2 = await redis_queue.dequeue(timeout=2.0)
    r3 = await redis_queue.dequeue(timeout=2.0)

    assert r1 is not None and r1.execution_id == "first"
    assert r2 is not None and r2.execution_id == "second"
    assert r3 is not None and r3.execution_id == "third"


async def test_consumer_group_auto_created(redis_container: str) -> None:
    """Consumer group is created automatically on initialize."""
    import uuid

    stream_key = f"ag:test:{uuid.uuid4().hex[:8]}"
    group = f"test-group-{uuid.uuid4().hex[:8]}"

    queue = RedisQueue(
        url=redis_container,
        stream_key=stream_key,
        consumer_group=group,
    )
    await queue.initialize()

    # Verify group exists by checking XINFO GROUPS
    groups = await queue._redis.xinfo_groups(stream_key)
    group_names = [g["name"] for g in groups]
    assert group in group_names

    await queue.dispose()
