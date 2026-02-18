"""Redis Streams queue backend for production async execution.

Requires: pip install agent-gateway[redis]

Uses Redis Streams with consumer groups for durable, distributed job processing.
Crash recovery via the Pending Entry List (PEL): unclaimed jobs are re-delivered
after ``visibility_timeout_s`` using XAUTOCLAIM.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_gateway.queue.models import ExecutionJob

logger = logging.getLogger(__name__)

_CANCEL_KEY_PREFIX = "ag:cancel:"
_CANCEL_TTL_S = 3600  # 1 hour — enough for any execution


class RedisQueue:
    """Redis Streams implementation of ExecutionQueue."""

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        stream_key: str = "ag:executions",
        consumer_group: str = "ag-workers",
        visibility_timeout_ms: int = 300_000,
    ) -> None:
        self._url = url
        self._stream_key = stream_key
        self._consumer_group = consumer_group
        self._visibility_timeout_ms = visibility_timeout_ms
        self._consumer_name: str = ""
        self._redis: Any = None

    async def initialize(self) -> None:
        """Connect to Redis and create consumer group."""
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self._url, decode_responses=True)

        # Generate a unique consumer name for this process
        import uuid

        self._consumer_name = f"worker-{uuid.uuid4().hex[:8]}"

        # Create consumer group (MKSTREAM creates the stream if it doesn't exist)
        try:
            await self._redis.xgroup_create(
                self._stream_key, self._consumer_group, id="0", mkstream=True
            )
        except Exception as e:
            # BUSYGROUP = group already exists, which is fine
            if "BUSYGROUP" not in str(e):
                raise

        # Recover stale entries from PEL on startup
        await self._recover_stale_entries()

        logger.info(
            "RedisQueue initialized: stream=%s, group=%s, consumer=%s",
            self._stream_key,
            self._consumer_group,
            self._consumer_name,
        )

    async def _recover_stale_entries(self) -> None:
        """Claim stale entries from the PEL using XAUTOCLAIM."""
        if self._redis is None:
            return
        try:
            # XAUTOCLAIM claims messages idle for longer than visibility_timeout_ms
            result = await self._redis.xautoclaim(
                self._stream_key,
                self._consumer_group,
                self._consumer_name,
                min_idle_time=self._visibility_timeout_ms,
                start_id="0-0",
                count=100,
            )
            if result and len(result) > 1 and result[1]:
                logger.info("Recovered %d stale entries from PEL", len(result[1]))
        except Exception:
            logger.warning("PEL recovery failed", exc_info=True)

    async def dispose(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def enqueue(self, job: ExecutionJob) -> None:
        """Add a job to the Redis stream."""
        if self._redis is None:
            raise RuntimeError("RedisQueue not initialized")
        await self._redis.xadd(
            self._stream_key,
            {"job": job.to_json()},
            id="*",
        )

    async def dequeue(self, timeout: float = 0) -> ExecutionJob | None:  # noqa: ASYNC109
        """Read next job from the stream via consumer group."""
        if self._redis is None:
            return None

        block_ms = int(timeout * 1000) if timeout > 0 else None

        results = await self._redis.xreadgroup(
            self._consumer_group,
            self._consumer_name,
            {self._stream_key: ">"},
            count=1,
            block=block_ms,
        )

        if not results:
            return None

        # results = [[stream_name, [(message_id, {field: value})]]]
        for _stream, messages in results:
            for msg_id, fields in messages:
                job_data = fields.get("job")
                if job_data is None:
                    # Malformed message, ack and skip
                    await self._redis.xack(self._stream_key, self._consumer_group, msg_id)
                    continue

                job = ExecutionJob.from_json(job_data)

                # Get delivery count from XPENDING for retry tracking
                try:
                    pending_info = await self._redis.xpending_range(
                        self._stream_key,
                        self._consumer_group,
                        min=msg_id,
                        max=msg_id,
                        count=1,
                    )
                    if pending_info:
                        delivery_count = pending_info[0].get("times_delivered", 1)
                        if delivery_count > 1:
                            # Create a new job with updated retry count
                            job = ExecutionJob(
                                execution_id=job.execution_id,
                                agent_id=job.agent_id,
                                message=job.message,
                                context=job.context,
                                timeout_ms=job.timeout_ms,
                                output_schema=job.output_schema,
                                enqueued_at=job.enqueued_at,
                                retry_count=delivery_count - 1,
                            )
                except Exception:
                    pass  # Retry count is best-effort

                # Store msg_id mapping for ack/nack
                await self._redis.hset(
                    f"ag:msg_map:{job.execution_id}", mapping={"msg_id": msg_id}
                )

                return job

        return None

    async def ack(self, job_id: str) -> None:
        """Acknowledge a job — removes from PEL."""
        if self._redis is None:
            return
        msg_id = await self._get_msg_id(job_id)
        if msg_id:
            await self._redis.xack(self._stream_key, self._consumer_group, msg_id)
            await self._redis.delete(f"ag:msg_map:{job_id}")
        # Clean up cancel key if present
        await self._redis.delete(f"{_CANCEL_KEY_PREFIX}{job_id}")

    async def nack(self, job_id: str) -> None:
        """Negative-acknowledge — let PEL handle re-delivery after visibility timeout."""
        if self._redis is None:
            return
        # For Redis Streams, we simply don't ack. The PEL will re-deliver
        # after the visibility timeout expires. Clean up the msg_id mapping.
        await self._redis.delete(f"ag:msg_map:{job_id}")

    async def request_cancel(self, job_id: str) -> bool:
        """Set a cancel key in Redis."""
        if self._redis is None:
            return False
        await self._redis.set(f"{_CANCEL_KEY_PREFIX}{job_id}", "1", ex=_CANCEL_TTL_S)
        return True

    async def is_cancelled(self, job_id: str) -> bool:
        """Check if the cancel key exists."""
        if self._redis is None:
            return False
        result = await self._redis.exists(f"{_CANCEL_KEY_PREFIX}{job_id}")
        return bool(result)

    async def length(self) -> int:
        """Return the stream length (approximate pending count)."""
        if self._redis is None:
            return 0
        return int(await self._redis.xlen(self._stream_key))

    async def _get_msg_id(self, job_id: str) -> str | None:
        """Look up the Redis message ID for a job."""
        if self._redis is None:
            return None
        result = await self._redis.hget(f"ag:msg_map:{job_id}", "msg_id")
        if result is None:
            return None
        return str(result)
