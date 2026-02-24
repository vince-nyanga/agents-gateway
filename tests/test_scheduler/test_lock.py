"""Tests for distributed lock backends."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_gateway.exceptions import SchedulerLockError
from agent_gateway.scheduler.lock import (
    NullDistributedLock,
    PostgresDistributedLock,
    RedisDistributedLock,
)


class TestNullDistributedLock:
    async def test_acquire_always_returns_true(self) -> None:
        lock = NullDistributedLock()
        assert await lock.acquire("test-lock", 300) is True

    async def test_release_is_noop(self) -> None:
        lock = NullDistributedLock()
        await lock.release("test-lock")  # should not raise

    async def test_initialize_and_dispose(self) -> None:
        lock = NullDistributedLock()
        await lock.initialize()
        await lock.dispose()


class TestRedisDistributedLock:
    async def test_acquire_succeeds_first_time(self) -> None:
        lock = RedisDistributedLock(url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.set.return_value = True
        lock._redis = mock_redis

        result = await lock.acquire("test-lock", 300)
        assert result is True
        mock_redis.set.assert_called_once_with("ag:sched-lock:test-lock", "1", nx=True, ex=300)

    async def test_acquire_fails_when_held(self) -> None:
        lock = RedisDistributedLock(url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.set.return_value = None
        lock._redis = mock_redis

        result = await lock.acquire("test-lock", 300)
        assert result is False

    async def test_release_deletes_key(self) -> None:
        lock = RedisDistributedLock(url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        lock._redis = mock_redis

        await lock.release("test-lock")
        mock_redis.delete.assert_called_once_with("ag:sched-lock:test-lock")

    async def test_acquire_raises_when_not_initialized(self) -> None:
        lock = RedisDistributedLock(url="redis://localhost:6379/0")
        with pytest.raises(SchedulerLockError, match="not initialized"):
            await lock.acquire("test-lock", 300)

    async def test_release_noop_when_not_initialized(self) -> None:
        lock = RedisDistributedLock(url="redis://localhost:6379/0")
        await lock.release("test-lock")  # should not raise

    async def test_dispose_closes_redis(self) -> None:
        lock = RedisDistributedLock(url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        lock._redis = mock_redis

        await lock.dispose()
        mock_redis.aclose.assert_called_once()
        assert lock._redis is None

    async def test_custom_key_prefix(self) -> None:
        lock = RedisDistributedLock(url="redis://localhost:6379/0", key_prefix="custom:")
        mock_redis = AsyncMock()
        mock_redis.set.return_value = True
        lock._redis = mock_redis

        await lock.acquire("my-lock", 60)
        mock_redis.set.assert_called_once_with("custom:my-lock", "1", nx=True, ex=60)


class TestPostgresDistributedLock:
    async def test_acquire_succeeds(self) -> None:
        mock_engine = AsyncMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value = mock_conn

        lock = PostgresDistributedLock(engine=mock_engine)
        result = await lock.acquire("test-lock", 300)

        assert result is True
        assert "test-lock" in lock._held_connections
        mock_conn.close.assert_not_called()

    async def test_acquire_fails_when_held(self) -> None:
        mock_engine = AsyncMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value = mock_conn

        lock = PostgresDistributedLock(engine=mock_engine)
        result = await lock.acquire("test-lock", 300)

        assert result is False
        assert "test-lock" not in lock._held_connections
        mock_conn.close.assert_called_once()

    async def test_release_unlocks_and_closes_connection(self) -> None:
        mock_conn = AsyncMock()
        lock = PostgresDistributedLock(engine=AsyncMock())
        lock._held_connections["test-lock"] = mock_conn

        await lock.release("test-lock")
        # Should call pg_advisory_unlock then close
        assert mock_conn.execute.call_count == 1
        call_args = mock_conn.execute.call_args
        text_clause = call_args[0][0]
        assert "pg_advisory_unlock" in text_clause.text
        mock_conn.close.assert_called_once()
        assert "test-lock" not in lock._held_connections

    async def test_release_noop_when_not_held(self) -> None:
        lock = PostgresDistributedLock(engine=AsyncMock())
        await lock.release("nonexistent")  # should not raise

    async def test_dispose_closes_all_held(self) -> None:
        conn1 = AsyncMock()
        conn2 = AsyncMock()
        lock = PostgresDistributedLock(engine=AsyncMock())
        lock._held_connections = {"lock-a": conn1, "lock-b": conn2}

        await lock.dispose()
        conn1.close.assert_called_once()
        conn2.close.assert_called_once()
        assert len(lock._held_connections) == 0
