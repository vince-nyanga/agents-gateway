"""Tests for ExecutionJob model."""

from __future__ import annotations

import pytest

from agent_gateway.queue.models import ExecutionJob


def test_job_round_trip_json() -> None:
    """ExecutionJob serialises to JSON and back without data loss."""
    job = ExecutionJob(
        execution_id="exec-1",
        agent_id="agent-a",
        message="Hello",
        context={"key": "value"},
        timeout_ms=30000,
        output_schema={"type": "object"},
        enqueued_at="2026-02-18T10:00:00+00:00",
        retry_count=2,
    )

    json_str = job.to_json()
    restored = ExecutionJob.from_json(json_str)

    assert restored == job


def test_job_round_trip_minimal() -> None:
    """Minimal job (only required fields) round-trips."""
    job = ExecutionJob(
        execution_id="exec-2",
        agent_id="agent-b",
        message="Hi",
    )

    restored = ExecutionJob.from_json(job.to_json())

    assert restored.execution_id == "exec-2"
    assert restored.agent_id == "agent-b"
    assert restored.message == "Hi"
    assert restored.context is None
    assert restored.timeout_ms is None
    assert restored.retry_count == 0


def test_job_is_frozen() -> None:
    """ExecutionJob is immutable."""
    job = ExecutionJob(execution_id="x", agent_id="a", message="m")
    with pytest.raises(AttributeError):
        job.execution_id = "y"  # type: ignore[misc]
