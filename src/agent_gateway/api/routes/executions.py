"""Execution history and control endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.models import ErrorDetail, ErrorResponse, ExecutionResponse
from agent_gateway.engine.models import ExecutionStatus

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

from agent_gateway.api.routes.base import GatewayAPIRoute

router = APIRouter(route_class=GatewayAPIRoute)


def _record_to_response(record) -> ExecutionResponse:  # type: ignore[no-untyped-def]
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
        started_at=record.started_at.isoformat() if record.started_at else None,
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
        created_at=record.created_at.isoformat() if record.created_at else None,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: str,
    request: Request,
) -> ExecutionResponse | JSONResponse:
    """Get execution details by ID."""
    gw: Gateway = request.app  # type: ignore[assignment]

    record = await gw._execution_repo.get(execution_id)
    if record is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="execution_not_found",
                    message=f"Execution '{execution_id}' not found",
                )
            ).model_dump(),
        )

    return _record_to_response(record)


@router.get("/executions", response_model=list[ExecutionResponse])
async def list_executions(
    request: Request,
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
) -> list[ExecutionResponse] | JSONResponse:
    """List executions, optionally filtered by agent."""
    gw: Gateway = request.app  # type: ignore[assignment]

    if agent_id:
        records = await gw._execution_repo.list_by_agent(agent_id, limit=limit)
    else:
        # list_by_agent with empty string won't work; use a general listing
        # For now, if no agent_id filter, return empty (full listing requires new repo method)
        records = await gw._execution_repo.list_by_agent("", limit=0)
        # TODO: add a list_all method to ExecutionRepository
        if agent_id is None:
            # For now return empty rather than error — will be enhanced later
            return []

    return [_record_to_response(r) for r in records]


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    request: Request,
) -> JSONResponse:
    """Cancel a running execution."""
    gw: Gateway = request.app  # type: ignore[assignment]

    handle = gw._execution_handles.get(execution_id)
    if handle is None:
        # Check if execution exists at all
        record = await gw._execution_repo.get(execution_id)
        if record is None:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error=ErrorDetail(
                        code="execution_not_found",
                        message=f"Execution '{execution_id}' not found",
                    )
                ).model_dump(),
            )
        # Execution exists but isn't running
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="invalid_state",
                    message=f"Execution '{execution_id}' is not running (status: {record.status})",
                    execution_id=execution_id,
                )
            ).model_dump(),
        )

    handle.cancel()
    await gw._execution_repo.update_status(execution_id, ExecutionStatus.CANCELLED)

    return JSONResponse(
        status_code=200,
        content={"execution_id": execution_id, "status": "cancelled"},
    )
