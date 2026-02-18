"""Shared status mapping utilities for API routes."""

from __future__ import annotations

from agent_gateway.engine.models import ExecutionStatus, StopReason


def stop_reason_to_status(stop_reason: StopReason) -> ExecutionStatus:
    """Map engine StopReason to API execution status."""
    mapping = {
        StopReason.COMPLETED: ExecutionStatus.COMPLETED,
        StopReason.MAX_ITERATIONS: ExecutionStatus.COMPLETED,
        StopReason.MAX_TOOL_CALLS: ExecutionStatus.COMPLETED,
        StopReason.TIMEOUT: ExecutionStatus.TIMEOUT,
        StopReason.CANCELLED: ExecutionStatus.CANCELLED,
        StopReason.ERROR: ExecutionStatus.FAILED,
    }
    return mapping.get(stop_reason, ExecutionStatus.FAILED)
