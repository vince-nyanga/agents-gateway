"""Distributed lock backends for scheduler duplicate-fire prevention.

When multiple gateway instances run behind a load balancer, each fires the
same cron job. A distributed lock ensures only one instance dispatches.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from agent_gateway.exceptions import SchedulerLockError

logger = logging.getLogger(__name__)


@runtime_checkable
class DistributedLock(Protocol):
    """Protocol for distributed scheduler locking."""

    async def initialize(self) -> None:
        """Set up connections."""
        ...

    async def dispose(self) -> None:
        """Release connections."""
        ...

    async def acquire(self, lock_name: str, ttl_seconds: int) -> bool:
        """Try to acquire a named lock. Returns True if acquired, False if held by another.

        Args:
            lock_name: Unique lock identifier (e.g. "schedule:agent:daily-report:1709078400").
            ttl_seconds: Auto-release after this many seconds (safety valve).
        """
        ...

    async def release(self, lock_name: str) -> None:
        """Release a named lock. No-op if not held."""
        ...


class NullDistributedLock:
    """No-op lock -- always succeeds. Used when distributed locking is disabled."""

    async def initialize(self) -> None:
        pass

    async def dispose(self) -> None:
        pass

    async def acquire(self, lock_name: str, ttl_seconds: int) -> bool:
        return True

    async def release(self, lock_name: str) -> None:
        pass


class RedisDistributedLock:
    """Redis-based distributed lock using SET NX EX."""

    def __init__(self, url: str, key_prefix: str = "ag:sched-lock:") -> None:
        self._url = url
        self._key_prefix = key_prefix
        self._redis: Any = None

    async def initialize(self) -> None:
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._url, decode_responses=True)
        except Exception as exc:
            raise SchedulerLockError(
                f"Failed to initialize Redis distributed lock: {exc}"
            ) from exc

    async def dispose(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def acquire(self, lock_name: str, ttl_seconds: int) -> bool:
        if self._redis is None:
            raise SchedulerLockError("RedisDistributedLock not initialized")
        key = f"{self._key_prefix}{lock_name}"
        try:
            result = await self._redis.set(key, "1", nx=True, ex=ttl_seconds)
            return result is not None
        except Exception as exc:
            raise SchedulerLockError(f"Failed to acquire Redis lock '{lock_name}': {exc}") from exc

    async def release(self, lock_name: str) -> None:
        if self._redis is None:
            return
        key = f"{self._key_prefix}{lock_name}"
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("Failed to release Redis lock '%s': %s", lock_name, exc)


class PostgresDistributedLock:
    """PostgreSQL advisory lock backend.

    Uses pg_try_advisory_lock with a hash of the lock name.
    Advisory locks are session-scoped, so we hold a dedicated connection
    for each active lock and release it explicitly.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._held_connections: dict[str, Any] = {}

    async def initialize(self) -> None:
        pass  # Engine is already initialized by persistence backend

    async def dispose(self) -> None:
        import contextlib

        for conn in self._held_connections.values():
            with contextlib.suppress(Exception):
                await conn.close()
        self._held_connections.clear()

    async def acquire(self, lock_name: str, ttl_seconds: int) -> bool:
        import hashlib

        from sqlalchemy import text

        lock_id = int(hashlib.sha256(lock_name.encode()).hexdigest()[:15], 16)

        try:
            conn = await self._engine.connect()
        except Exception as exc:
            raise SchedulerLockError(
                f"Failed to connect for advisory lock '{lock_name}': {exc}"
            ) from exc

        try:
            result = await conn.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": lock_id},
            )
            acquired = result.scalar()
            if acquired:
                self._held_connections[lock_name] = conn
                return True
            else:
                await conn.close()
                return False
        except Exception as exc:
            await conn.close()
            raise SchedulerLockError(
                f"Failed to acquire advisory lock '{lock_name}': {exc}"
            ) from exc

    async def release(self, lock_name: str) -> None:
        conn = self._held_connections.pop(lock_name, None)
        if conn is not None:
            try:
                import hashlib

                from sqlalchemy import text

                lock_id = int(hashlib.sha256(lock_name.encode()).hexdigest()[:15], 16)
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": lock_id},
                )
            except Exception as exc:
                logger.warning("Failed to release advisory lock '%s': %s", lock_name, exc)
            finally:
                await conn.close()
