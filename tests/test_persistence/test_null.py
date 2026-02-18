"""Tests for NullPersistence fallback implementations."""

from __future__ import annotations

from agent_gateway.persistence.models import ExecutionRecord, ExecutionStep
from agent_gateway.persistence.null import NullAuditRepository, NullExecutionRepository


async def test_null_execution_create():
    """NullExecutionRepository.create should be a no-op."""
    repo = NullExecutionRepository()
    record = ExecutionRecord(id="x", agent_id="a", status="running", message="hi")
    await repo.create(record)  # Should not raise


async def test_null_execution_get():
    """NullExecutionRepository.get should always return None."""
    repo = NullExecutionRepository()
    result = await repo.get("any-id")
    assert result is None


async def test_null_execution_update_status():
    """NullExecutionRepository.update_status should be a no-op."""
    repo = NullExecutionRepository()
    await repo.update_status("x", "completed")  # Should not raise


async def test_null_execution_update_result():
    """NullExecutionRepository.update_result should be a no-op."""
    repo = NullExecutionRepository()
    await repo.update_result("x", {}, {})  # Should not raise


async def test_null_execution_list_by_agent():
    """NullExecutionRepository.list_by_agent should return empty list."""
    repo = NullExecutionRepository()
    result = await repo.list_by_agent("any-agent")
    assert result == []


async def test_null_execution_add_step():
    """NullExecutionRepository.add_step should be a no-op."""
    repo = NullExecutionRepository()
    step = ExecutionStep(execution_id="x", step_type="llm_call", sequence=1)
    await repo.add_step(step)  # Should not raise


async def test_null_audit_log():
    """NullAuditRepository.log should be a no-op."""
    repo = NullAuditRepository()
    await repo.log(event_type="test.event")  # Should not raise


async def test_null_audit_list_recent():
    """NullAuditRepository.list_recent should return empty list."""
    repo = NullAuditRepository()
    result = await repo.list_recent()
    assert result == []
