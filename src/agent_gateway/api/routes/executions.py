"""Execution history and control endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response
from agent_gateway.api.models import ExecutionResponse
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.auth.scopes import RequireScope
from agent_gateway.engine.models import ExecutionStatus
from agent_gateway.persistence.domain import ExecutionRecord
from agent_gateway.queue.null import NullQueue

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

_TERMINAL_STATUSES = frozenset(
    {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMEOUT,
    }
)

router = APIRouter(route_class=GatewayAPIRoute)


def _record_to_response(record: ExecutionRecord) -> ExecutionResponse:
    """Convert a DB ExecutionRecord to an API response."""
    return ExecutionResponse(
        execution_id=record.id,
        agent_id=record.agent_id,
        status=record.status,
        message=record.message,
        input=record.input,
        result=record.result,
        error=record.error,
        usage=record.usage,
        session_id=record.session_id,
        parent_execution_id=record.parent_execution_id,
        root_execution_id=record.root_execution_id,
        delegation_depth=record.delegation_depth,
        started_at=record.started_at,
        completed_at=record.completed_at,
        created_at=record.created_at,
    )


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionResponse,
    dependencies=[Depends(RequireScope("executions:read"))],
)
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


@router.get(
    "/executions",
    response_model=list[ExecutionResponse],
    dependencies=[Depends(RequireScope("executions:read"))],
)
async def list_executions(
    request: Request,
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    session_id: str | None = Query(None, description="Filter by session/conversation ID"),
    root_execution_id: str | None = Query(
        None, description="Filter by root execution ID (delegation tree)"
    ),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
) -> list[ExecutionResponse]:
    """List executions, optionally filtered by agent, session, or delegation tree."""
    gw: Gateway = request.app

    if root_execution_id:
        records = await gw._execution_repo.list_by_root_execution(root_execution_id)
        return [_record_to_response(r) for r in records[:limit]]

    if session_id:
        records = await gw._execution_repo.list_by_session(session_id, limit=limit)
        return [_record_to_response(r) for r in records]

    if agent_id:
        records = await gw._execution_repo.list_by_agent(agent_id, limit=limit)
        return [_record_to_response(r) for r in records]

    records = await gw._execution_repo.list_all(limit=limit)
    return [_record_to_response(r) for r in records]


@router.get(
    "/executions/{execution_id}/workflow",
    response_model=list[ExecutionResponse],
    dependencies=[Depends(RequireScope("executions:read"))],
)
async def get_execution_workflow(
    request: Request,
    execution_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> list[ExecutionResponse] | JSONResponse:
    """Get the full delegation workflow tree for an execution."""
    gw: Gateway = request.app

    record = await gw._execution_repo.get(execution_id)
    if record is None:
        return error_response(404, "execution_not_found", f"Execution '{execution_id}' not found")

    # Use root_execution_id if available, otherwise this is the root
    root_id = record.root_execution_id or execution_id
    records = await gw._execution_repo.list_by_root_execution(root_id)

    # If no records found via root query, return just the single record
    if not records:
        return [_record_to_response(record)]

    return [_record_to_response(r) for r in records]


@router.post(
    "/executions/{execution_id}/cancel",
    dependencies=[Depends(RequireScope("executions:cancel"))],
)
async def cancel_execution(
    request: Request,
    execution_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> JSONResponse:
    """Cancel a running or queued execution."""
    gw: Gateway = request.app

    # 1. Try in-memory handle (sync execution or same-process worker)
    handle = gw._execution_handles.get(execution_id)
    if handle is not None:
        handle.cancel()
        await gw._execution_repo.update_status(execution_id, ExecutionStatus.CANCELLED)
        return JSONResponse(
            status_code=200,
            content={"execution_id": execution_id, "status": "cancelled"},
        )

    # 2. Try queue backend (queued job or running on another worker)
    if not isinstance(gw._queue, NullQueue):
        cancelled = await gw._queue.request_cancel(execution_id)
        if cancelled:
            await gw._execution_repo.update_status(execution_id, ExecutionStatus.CANCELLED)
            return JSONResponse(
                status_code=200,
                content={"execution_id": execution_id, "status": "cancel_requested"},
            )

    # 3. Check persistence for terminal or unknown state
    record = await gw._execution_repo.get(execution_id)
    if record is None:
        return error_response(404, "execution_not_found", f"Execution '{execution_id}' not found")

    if record.status in _TERMINAL_STATUSES:
        return error_response(
            409,
            "invalid_state",
            f"Execution '{execution_id}' already in terminal state: {record.status}",
        )

    return error_response(
        409,
        "invalid_state",
        f"Execution '{execution_id}' is not cancellable (status: {record.status})",
    )
