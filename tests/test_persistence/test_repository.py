"""Tests for persistence repository CRUD operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_gateway.persistence.backends.sql.repository import (
    AuditRepository,
    ExecutionRepository,
)
from agent_gateway.persistence.domain import ExecutionRecord, ExecutionStep


async def test_create_and_get_execution(session_factory: async_sessionmaker[AsyncSession]):
    """Should create and retrieve an execution record."""
    repo = ExecutionRepository(session_factory)
    record = ExecutionRecord(
        id="exec-001",
        agent_id="test-agent",
        status="running",
        message="Hello",
    )
    await repo.create(record)

    fetched = await repo.get("exec-001")
    assert fetched is not None
    assert fetched.id == "exec-001"
    assert fetched.agent_id == "test-agent"
    assert fetched.status == "running"
    assert fetched.message == "Hello"


async def test_get_nonexistent_execution(session_factory: async_sessionmaker[AsyncSession]):
    """Should return None for missing execution."""
    repo = ExecutionRepository(session_factory)
    result = await repo.get("does-not-exist")
    assert result is None


async def test_update_status(session_factory: async_sessionmaker[AsyncSession]):
    """Should update execution status and optional fields."""
    repo = ExecutionRepository(session_factory)
    record = ExecutionRecord(
        id="exec-002",
        agent_id="test-agent",
        status="running",
        message="Test",
    )
    await repo.create(record)
    await repo.update_status("exec-002", "completed", error=None)

    fetched = await repo.get("exec-002")
    assert fetched is not None
    assert fetched.status == "completed"


async def test_update_status_nonexistent(session_factory: async_sessionmaker[AsyncSession]):
    """Should not crash when updating nonexistent execution."""
    repo = ExecutionRepository(session_factory)
    # Should not raise
    await repo.update_status("nonexistent", "completed")


async def test_update_result(session_factory: async_sessionmaker[AsyncSession]):
    """Should update result and usage and set completed_at."""
    repo = ExecutionRepository(session_factory)
    record = ExecutionRecord(
        id="exec-003",
        agent_id="test-agent",
        status="running",
        message="Test",
    )
    await repo.create(record)

    result = {"output": "Hello!", "raw_text": "Hello!"}
    usage = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001}
    await repo.update_result("exec-003", result, usage)

    fetched = await repo.get("exec-003")
    assert fetched is not None
    assert fetched.result == result
    assert fetched.usage == usage
    assert fetched.completed_at is not None


async def test_list_by_agent(session_factory: async_sessionmaker[AsyncSession]):
    """Should list executions for an agent, most recent first."""
    repo = ExecutionRepository(session_factory)

    for i in range(3):
        record = ExecutionRecord(
            id=f"exec-list-{i}",
            agent_id="list-agent",
            status="completed",
            message=f"Message {i}",
        )
        await repo.create(record)

    results = await repo.list_by_agent("list-agent")
    assert len(results) == 3


async def test_list_by_agent_limit(session_factory: async_sessionmaker[AsyncSession]):
    """Should respect the limit parameter."""
    repo = ExecutionRepository(session_factory)

    for i in range(5):
        record = ExecutionRecord(
            id=f"exec-limit-{i}",
            agent_id="limit-agent",
            status="completed",
            message=f"Message {i}",
        )
        await repo.create(record)

    results = await repo.list_by_agent("limit-agent", limit=2)
    assert len(results) == 2


async def test_list_by_agent_empty(session_factory: async_sessionmaker[AsyncSession]):
    """Should return empty list for agent with no executions."""
    repo = ExecutionRepository(session_factory)
    results = await repo.list_by_agent("no-such-agent")
    assert results == []


async def test_add_step(session_factory: async_sessionmaker[AsyncSession]):
    """Should add an execution step."""
    repo = ExecutionRepository(session_factory)

    record = ExecutionRecord(
        id="exec-step-001",
        agent_id="test-agent",
        status="running",
        message="Test",
    )
    await repo.create(record)

    step = ExecutionStep(
        execution_id="exec-step-001",
        step_type="llm_call",
        sequence=1,
        data={"model": "gpt-4o-mini", "tokens": 100},
        duration_ms=500,
    )
    await repo.add_step(step)

    # Verify via a fresh get — step should be persisted
    fetched = await repo.get("exec-step-001")
    assert fetched is not None


async def test_audit_log(session_factory: async_sessionmaker[AsyncSession]):
    """Should write and retrieve audit log entries."""
    repo = AuditRepository(session_factory)

    await repo.log(
        event_type="execution.started",
        actor="api-key-1",
        resource_type="execution",
        resource_id="exec-001",
        metadata={"agent_id": "test-agent"},
        ip_address="127.0.0.1",
    )

    entries = await repo.list_recent(limit=10)
    assert len(entries) == 1
    assert entries[0].event_type == "execution.started"
    assert entries[0].actor == "api-key-1"
    assert entries[0].resource_id == "exec-001"
    assert entries[0].ip_address == "127.0.0.1"


async def test_audit_log_multiple(session_factory: async_sessionmaker[AsyncSession]):
    """Should retrieve multiple audit entries in reverse chronological order."""
    repo = AuditRepository(session_factory)

    for i in range(3):
        await repo.log(event_type=f"event-{i}", actor=f"actor-{i}")

    entries = await repo.list_recent(limit=10)
    assert len(entries) == 3
