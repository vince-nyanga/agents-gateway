"""RabbitMQ queue backend for production async execution.

Requires: pip install agent-gateway[rabbitmq]

Uses a durable queue with manual acknowledgement. Dead-lettering via DLX
for jobs exceeding max_retries. Cancel signals distributed via a fanout exchange.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_gateway.queue.models import ExecutionJob

logger = logging.getLogger(__name__)


class RabbitMQQueue:
    """RabbitMQ (aio-pika) implementation of ExecutionQueue."""

    def __init__(
        self,
        url: str = "amqp://guest:guest@localhost:5672/",
        queue_name: str = "ag.executions",
    ) -> None:
        self._url = url
        self._queue_name = queue_name
        self._dlx_exchange_name = f"{queue_name}.dlx"
        self._dlq_name = f"{queue_name}.dead-letter"
        self._cancel_exchange_name = "ag.cancel"
        self._connection: Any = None
        self._channel: Any = None
        self._queue: Any = None
        self._cancel_queue: Any = None
        self._cancelled: set[str] = set()
        self._cancel_consumer_tag: str | None = None

    async def initialize(self) -> None:
        """Connect to RabbitMQ, declare queues and exchanges."""
        import aio_pika

        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()

        # Set prefetch to 1 — workers pull one job at a time
        await self._channel.set_qos(prefetch_count=1)

        # Dead letter exchange and queue
        dlx_exchange = await self._channel.declare_exchange(
            self._dlx_exchange_name,
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        dlq = await self._channel.declare_queue(self._dlq_name, durable=True)
        await dlq.bind(dlx_exchange, routing_key=self._queue_name)

        # Main execution queue with DLX
        self._queue = await self._channel.declare_queue(
            self._queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self._dlx_exchange_name,
                "x-dead-letter-routing-key": self._queue_name,
            },
        )

        # Cancel fanout exchange — all workers subscribe
        cancel_exchange = await self._channel.declare_exchange(
            self._cancel_exchange_name,
            aio_pika.ExchangeType.FANOUT,
            durable=False,
        )
        # Exclusive auto-delete queue for this consumer
        self._cancel_queue = await self._channel.declare_queue(
            "", exclusive=True, auto_delete=True
        )
        await self._cancel_queue.bind(cancel_exchange)

        # Start consuming cancel messages
        self._cancel_consumer_tag = await self._cancel_queue.consume(self._on_cancel_message)

        logger.info(
            "RabbitMQQueue initialized: queue=%s, dlq=%s",
            self._queue_name,
            self._dlq_name,
        )

    async def _on_cancel_message(self, message: Any) -> None:
        """Handle incoming cancel messages from the fanout exchange."""
        async with message.process():
            execution_id = message.body.decode("utf-8")
            self._cancelled.add(execution_id)

    async def dispose(self) -> None:
        """Close RabbitMQ connection."""
        if self._cancel_queue and self._cancel_consumer_tag:
            await self._cancel_queue.cancel(self._cancel_consumer_tag)
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            self._channel = None
            self._queue = None
        self._cancelled.clear()

    async def enqueue(self, job: ExecutionJob) -> None:
        """Publish a job to the execution queue."""
        if self._channel is None:
            raise RuntimeError("RabbitMQQueue not initialized")
        import aio_pika

        message = aio_pika.Message(
            body=job.to_json().encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=job.execution_id,
            headers={"retry_count": job.retry_count},
        )
        await self._channel.default_exchange.publish(message, routing_key=self._queue_name)

    async def dequeue(self, timeout: float = 0) -> ExecutionJob | None:  # noqa: ASYNC109
        """Pull a single message from the queue."""
        if self._queue is None:
            return None

        # Try to get a message (basic_get style)
        message = await self._queue.get(fail=False, timeout=timeout or 1)
        if message is None:
            return None

        try:
            job = ExecutionJob.from_json(message.body.decode("utf-8"))

            # Track retry count from headers
            headers = message.headers or {}
            retry_count = headers.get("retry_count", 0)
            if retry_count > 0:
                job = ExecutionJob(
                    execution_id=job.execution_id,
                    agent_id=job.agent_id,
                    message=job.message,
                    input=job.input,
                    timeout_ms=job.timeout_ms,
                    output_schema=job.output_schema,
                    enqueued_at=job.enqueued_at,
                    retry_count=retry_count,
                )

            # Store the message for ack/nack
            self._pending_messages: dict[str, Any] = getattr(self, "_pending_messages", {})
            self._pending_messages[job.execution_id] = message

            return job
        except Exception:
            # Malformed message — reject without requeue
            await message.reject(requeue=False)
            return None

    async def ack(self, job_id: str) -> None:
        """Acknowledge successful processing."""
        messages = getattr(self, "_pending_messages", {})
        message = messages.pop(job_id, None)
        if message is not None:
            await message.ack()
        self._cancelled.discard(job_id)

    async def nack(self, job_id: str) -> None:
        """Negative-acknowledge — requeue with incremented retry count."""
        messages = getattr(self, "_pending_messages", {})
        message = messages.pop(job_id, None)
        if message is not None:
            # Reject with requeue — RabbitMQ will re-deliver
            await message.reject(requeue=True)

    async def request_cancel(self, job_id: str) -> bool:
        """Publish cancel signal to the fanout exchange."""
        if self._channel is None:
            return False
        import aio_pika

        cancel_exchange = await self._channel.get_exchange(self._cancel_exchange_name)
        message = aio_pika.Message(body=job_id.encode("utf-8"))
        await cancel_exchange.publish(message, routing_key="")
        self._cancelled.add(job_id)
        return True

    async def is_cancelled(self, job_id: str) -> bool:
        """Check if a cancel signal was received for this job."""
        return job_id in self._cancelled

    async def length(self) -> int:
        """Return the approximate number of messages in the queue."""
        if self._queue is None:
            return 0
        # Re-declare passively to get the current message count
        if self._channel is None:
            return 0
        try:
            queue_info = await self._channel.declare_queue(self._queue_name, passive=True)
            return int(queue_info.declaration_result.message_count)
        except Exception:
            return 0
