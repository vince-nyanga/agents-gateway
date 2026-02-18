"""Agent invocation endpoint."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.models import (
    ErrorDetail,
    ErrorResponse,
    InvokeRequest,
    InvokeResponse,
    ResultPayload,
    UsagePayload,
)
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
    ExecutionStatus,
    StopReason,
)
from agent_gateway.persistence.models import ExecutionRecord
from agent_gateway.tools.runner import execute_tool

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)


def _stop_reason_to_status(stop_reason: StopReason) -> str:
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


def _build_response(
    execution_id: str,
    agent_id: str,
    result: ExecutionResult,
    duration_ms: int,
) -> InvokeResponse:
    """Build the API response from an ExecutionResult."""
    status = _stop_reason_to_status(result.stop_reason)
    usage_dict = result.usage.to_dict()

    return InvokeResponse(
        execution_id=execution_id,
        agent_id=agent_id,
        status=status,
        result=ResultPayload(
            output=result.output,
            raw_text=result.raw_text,
            validation_errors=result.validation_errors,
        ),
        usage=UsagePayload(
            input_tokens=usage_dict.get("input_tokens", 0),
            output_tokens=usage_dict.get("output_tokens", 0),
            cost_usd=usage_dict.get("cost_usd", 0.0),
            llm_calls=usage_dict.get("llm_calls", 0),
            tool_calls=usage_dict.get("tool_calls", 0),
            models_used=usage_dict.get("models_used", []),
            duration_ms=duration_ms,
        ),
        error=result.error,
    )


@router.post("/agents/{agent_id}/invoke", response_model=InvokeResponse)
async def invoke_agent(
    agent_id: str,
    body: InvokeRequest,
    request: Request,
) -> InvokeResponse | JSONResponse:
    """Invoke an agent with a message."""
    gw: Gateway = request.app  # type: ignore[assignment]

    # Check workspace is loaded
    if gw._workspace is None:
        return _error_response(503, "workspace_unavailable", "Workspace not loaded")

    # Look up agent
    agent = gw._workspace.agents.get(agent_id)
    if agent is None:
        available = sorted(gw._workspace.agents.keys())
        return _error_response(
            404,
            "agent_not_found",
            f"Agent '{agent_id}' not found. Available: {', '.join(available)}",
        )

    # Check engine is available
    if gw._engine is None:
        return _error_response(503, "engine_unavailable", "Execution engine not initialized")

    # Generate execution ID
    execution_id = getattr(request.state, "execution_id", None) or str(uuid.uuid4())

    # Build execution options
    exec_options = ExecutionOptions(
        async_execution=body.options.async_,
        timeout_ms=body.options.timeout_ms,
        stream=body.options.stream,
    )

    # Create execution record
    record = ExecutionRecord(
        id=execution_id,
        agent_id=agent_id,
        status=ExecutionStatus.RUNNING,
        message=body.message,
        context=body.context or None,
        started_at=datetime.now(UTC),
    )
    await gw._execution_repo.create(record)

    # Async execution: start background task, return 202
    if body.options.async_:
        handle = ExecutionHandle(execution_id)
        gw._execution_handles[execution_id] = handle
        asyncio.create_task(
            _run_background_execution(
                gw, agent, body, execution_id, exec_options, handle
            )
        )
        return JSONResponse(
            status_code=202,
            content=InvokeResponse(
                execution_id=execution_id,
                agent_id=agent_id,
                status=ExecutionStatus.QUEUED,
            ).model_dump(),
        )

    # Synchronous execution
    handle = ExecutionHandle(execution_id)
    gw._execution_handles[execution_id] = handle
    start = time.monotonic()

    try:
        result = await gw._engine.execute(
            agent=agent,
            message=body.message,
            workspace=gw._workspace,
            context=body.context,
            options=exec_options,
            handle=handle,
            tool_executor=execute_tool,
        )
    except Exception as e:
        logger.error("Execution failed: %s", e)
        await gw._execution_repo.update_status(
            execution_id, ExecutionStatus.FAILED, error=str(e)
        )
        return _error_response(
            500, "execution_error", "Internal execution error", execution_id=execution_id
        )
    finally:
        gw._execution_handles.pop(execution_id, None)

    duration_ms = int((time.monotonic() - start) * 1000)

    # Persist result
    status = _stop_reason_to_status(result.stop_reason)
    await gw._execution_repo.update_status(
        execution_id,
        status,
        completed_at=datetime.now(UTC),
    )
    await gw._execution_repo.update_result(
        execution_id,
        result=result.to_dict(),
        usage=result.usage.to_dict(),
    )

    return _build_response(execution_id, agent_id, result, duration_ms)


async def _run_background_execution(
    gw: Gateway,
    agent: Any,
    body: InvokeRequest,
    execution_id: str,
    options: ExecutionOptions,
    handle: ExecutionHandle,
) -> None:
    """Run an agent execution as a background task."""
    try:
        await gw._execution_repo.update_status(execution_id, ExecutionStatus.RUNNING)

        result = await gw._engine.execute(  # type: ignore[union-attr]
            agent=agent,
            message=body.message,
            workspace=gw._workspace,  # type: ignore[arg-type]
            context=body.context,
            options=options,
            handle=handle,
            tool_executor=execute_tool,
        )

        status = _stop_reason_to_status(result.stop_reason)
        await gw._execution_repo.update_status(
            execution_id, status, completed_at=datetime.now(UTC)
        )
        await gw._execution_repo.update_result(
            execution_id,
            result=result.to_dict(),
            usage=result.usage.to_dict(),
        )
    except Exception as e:
        logger.error("Background execution %s failed: %s", execution_id, e)
        await gw._execution_repo.update_status(
            execution_id, ExecutionStatus.FAILED, error=str(e)
        )
    finally:
        gw._execution_handles.pop(execution_id, None)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    execution_id: str | None = None,
) -> JSONResponse:
    """Build a standard error JSONResponse."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=code,
                message=message,
                execution_id=execution_id,
            )
        ).model_dump(),
    )
