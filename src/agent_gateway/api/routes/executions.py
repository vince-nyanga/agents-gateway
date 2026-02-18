"""Execution history and control endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response
from agent_gateway.api.models import ExecutionResponse
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.engine.models import ExecutionStatus
from agent_gateway.persistence.domain import ExecutionRecord

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

router = APIRouter(route_class=GatewayAPIRoute)


def _record_to_response(record: ExecutionRecord) -> ExecutionResponse:
    """Convert a DB ExecutionRecord to an API response."""
    return ExecutionResponse(
        execution_id=record.id,
        agent_id=record.agent_id,
        status=record.status,
        message=record.message,
        context=record.context,
        result=record.result,
        error=record.error,
        usage=record.usage,
        started_at=record.started_at,
        completed_at=record.completed_at,
        created_at=record.created_at,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    request: Request,
    execution_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> ExecutionResponse | JSONResponse:
    """Get execution details by ID."""
    gw: Gateway = request.app

    record = await gw._execution_repo.get(execution_id)
    if record is None:
        return error_response(404, "execution_not_found", f"Execution '{execution_id}' not found")

    return _record_to_response(record)


@router.get("/executions", response_model=list[ExecutionResponse])
async def list_executions(
    request: Request,
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
) -> list[ExecutionResponse]:
    """List executions, optionally filtered by agent."""
    gw: Gateway = request.app

    if not agent_id:
        # TODO: add a list_all method to ExecutionRepository
        return []

    records = await gw._execution_repo.list_by_agent(agent_id, limit=limit)
    return [_record_to_response(r) for r in records]


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    request: Request,
    execution_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> JSONResponse:
    """Cancel a running execution."""
    gw: Gateway = request.app

    handle = gw._execution_handles.get(execution_id)
    if handle is None:
        record = await gw._execution_repo.get(execution_id)
        if record is None:
            return error_response(
                404, "execution_not_found", f"Execution '{execution_id}' not found"
            )
        return error_response(
            409,
            "invalid_state",
            f"Execution '{execution_id}' is not running (status: {record.status})",
        )

    handle.cancel()
    await gw._execution_repo.update_status(execution_id, ExecutionStatus.CANCELLED)

    return JSONResponse(
        status_code=200,
        content={"execution_id": execution_id, "status": "cancelled"},
    )
