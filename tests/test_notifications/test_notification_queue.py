"""Tests for notification queue — job model, queue backends, and worker integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from agent_gateway.notifications.models import (
    AgentNotificationConfig,
    NotificationJob,
    NotificationTarget,
    build_notification_job,
)
from agent_gateway.notifications.queue_backends import MemoryNotificationQueue
from agent_gateway.notifications.worker import NotificationWorker


class TestNotificationJobSerialization:
    """Round-trip serialization for NotificationJob."""

    def test_round_trip_minimal(self) -> None:
        job = NotificationJob(
            job_id="j-1",
            execution_id="e-1",
            agent_id="agent-1",
            status="completed",
            message="hello",
            config={"on_complete": [], "on_error": [], "on_timeout": []},
        )
        restored = NotificationJob.from_json(job.to_json())
        assert restored == job

    def test_round_trip_full(self) -> None:
        job = NotificationJob(
            job_id="j-2",
            execution_id="e-2",
            agent_id="agent-2",
            status="failed",
            message="run this",
            config={
                "on_complete": [],
                "on_error": [{"channel": "webhook", "url": "https://example.com/hook"}],
                "on_timeout": [],
            },
            result={"output": "stuff"},
            error="boom",
            usage={"input_tokens": 100, "output_tokens": 50},
            duration_ms=1500,
            input={"user": "alice"},
            enqueued_at="2026-01-01T00:00:00Z",
        )
        restored = NotificationJob.from_json(job.to_json())
        assert restored == job

    def test_from_json_missing_optionals(self) -> None:
        """Omitted optional fields default correctly."""
        import json

        data = json.dumps(
            {
                "job_id": "j-3",
                "execution_id": "e-3",
                "agent_id": "a-3",
                "status": "completed",
                "message": "hi",
                "config": {"on_complete": [], "on_error": [], "on_timeout": []},
            }
        )
        job = NotificationJob.from_json(data)
        assert job.result is None
        assert job.error is None
        assert job.usage is None
        assert job.duration_ms == 0
        assert job.input is None
        assert job.enqueued_at == ""


class TestBuildNotificationJob:
    def test_factory_serializes_config(self) -> None:
        config = AgentNotificationConfig(
            on_complete=[NotificationTarget(channel="webhook", url="https://example.com")],
        )
        job = build_notification_job(
            job_id="j-1",
            execution_id="e-1",
            agent_id="a-1",
            status="completed",
            message="hello",
            config=config,
        )
        assert job.config == config.to_dict()
        assert job.config["on_complete"][0]["channel"] == "webhook"


class TestNotificationTargetSerialization:
    def test_round_trip(self) -> None:
        target = NotificationTarget(
            channel="webhook",
            target="crm",
            url="https://example.com/hook",
            payload_template="{{ event.status }}",
        )
        restored = NotificationTarget.from_dict(target.to_dict())
        assert restored == target

    def test_minimal(self) -> None:
        target = NotificationTarget(channel="slack", target="#alerts")
        restored = NotificationTarget.from_dict(target.to_dict())
        assert restored == target


class TestAgentNotificationConfigSerialization:
    def test_round_trip(self) -> None:
        config = AgentNotificationConfig(
            on_complete=[NotificationTarget(channel="slack", target="#done")],
            on_error=[NotificationTarget(channel="webhook", url="https://err.example.com")],
            on_timeout=[],
        )
        restored = AgentNotificationConfig.from_dict(config.to_dict())
        assert restored.on_complete == config.on_complete
        assert restored.on_error == config.on_error
        assert restored.on_timeout == config.on_timeout

    def test_empty_config(self) -> None:
        config = AgentNotificationConfig()
        restored = AgentNotificationConfig.from_dict(config.to_dict())
        assert restored.on_complete == []
        assert restored.on_error == []
        assert restored.on_timeout == []


class TestMemoryNotificationQueue:
    async def test_enqueue_dequeue(self) -> None:
        q = MemoryNotificationQueue()
        await q.initialize()

        job = NotificationJob(
            job_id="j-1",
            execution_id="e-1",
            agent_id="a-1",
            status="completed",
            message="hello",
            config={"on_complete": [], "on_error": [], "on_timeout": []},
        )
        await q.enqueue(job)
        assert await q.length() == 1

        dequeued = await q.dequeue()
        assert dequeued is not None
        assert dequeued.job_id == "j-1"
        assert await q.length() == 0

        await q.dispose()

    async def test_dequeue_empty_returns_none(self) -> None:
        q = MemoryNotificationQueue()
        await q.initialize()

        result = await q.dequeue()
        assert result is None

        await q.dispose()

    async def test_dequeue_with_timeout_returns_none(self) -> None:
        q = MemoryNotificationQueue()
        await q.initialize()

        result = await q.dequeue(timeout=0.05)
        assert result is None

        await q.dispose()

    async def test_ack_nack_are_noops(self) -> None:
        q = MemoryNotificationQueue()
        await q.initialize()

        # Should not raise
        await q.ack("nonexistent")
        await q.nack("nonexistent")

        await q.dispose()

    async def test_fifo_order(self) -> None:
        q = MemoryNotificationQueue()
        await q.initialize()

        for i in range(3):
            job = NotificationJob(
                job_id=f"j-{i}",
                execution_id=f"e-{i}",
                agent_id="a-1",
                status="completed",
                message="hello",
                config={"on_complete": [], "on_error": [], "on_timeout": []},
            )
            await q.enqueue(job)

        for i in range(3):
            dequeued = await q.dequeue()
            assert dequeued is not None
            assert dequeued.job_id == f"j-{i}"

        await q.dispose()


class TestNotificationWorkerIntegration:
    """Integration test: enqueue a notification job, worker consumes and delivers."""

    async def test_worker_consumes_and_delivers(self) -> None:
        queue = MemoryNotificationQueue()
        await queue.initialize()

        engine = AsyncMock()
        engine.notify = AsyncMock()

        worker = NotificationWorker(queue=queue, engine=engine)
        await worker.start()

        config = AgentNotificationConfig(
            on_complete=[NotificationTarget(channel="webhook", url="https://example.com/hook")],
        )
        job = build_notification_job(
            job_id="j-1",
            execution_id="e-1",
            agent_id="a-1",
            status="completed",
            message="hello",
            config=config,
        )
        await queue.enqueue(job)

        # Give the worker time to process
        await asyncio.sleep(0.1)

        await worker.drain()
        await queue.dispose()

        engine.notify.assert_awaited_once()
        call_args = engine.notify.call_args
        event = call_args[0][0]
        assert event.execution_id == "e-1"
        assert event.type == "execution.completed"
        notif_config = call_args[0][1]
        assert len(notif_config.on_complete) == 1
        assert notif_config.on_complete[0].url == "https://example.com/hook"

    async def test_worker_nacks_on_engine_failure(self) -> None:
        queue = MemoryNotificationQueue()
        await queue.initialize()

        engine = AsyncMock()
        engine.notify = AsyncMock(side_effect=RuntimeError("engine crash"))

        worker = NotificationWorker(queue=queue, engine=engine)
        await worker.start()

        config = AgentNotificationConfig()
        job = build_notification_job(
            job_id="j-2",
            execution_id="e-2",
            agent_id="a-2",
            status="failed",
            message="boom",
            config=config,
        )
        await queue.enqueue(job)

        await asyncio.sleep(0.1)
        await worker.drain()
        await queue.dispose()

        # Engine was called (and failed)
        engine.notify.assert_awaited_once()

    async def test_worker_handles_empty_queue_gracefully(self) -> None:
        queue = MemoryNotificationQueue()
        await queue.initialize()

        engine = AsyncMock()
        worker = NotificationWorker(queue=queue, engine=engine)
        await worker.start()

        # Let it loop a couple times with no jobs
        await asyncio.sleep(0.15)

        await worker.drain()
        await queue.dispose()

        engine.notify.assert_not_awaited()
