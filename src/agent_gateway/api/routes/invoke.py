"""Agent invocation endpoint."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response
from agent_gateway.api.models import (
    InvokeRequest,
    InvokeResponse,
    ResultPayload,
    UsagePayload,
)
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.api.routes.status import stop_reason_to_status
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
    ExecutionStatus,
)
from agent_gateway.persistence.domain import ExecutionRecord
from agent_gateway.tools.runner import execute_tool

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)


def _build_response(
    execution_id: str,
    agent_id: str,
    result: ExecutionResult,
    duration_ms: int,
) -> InvokeResponse:
    """Build the API response from an ExecutionResult."""
    status = stop_reason_to_status(result.stop_reason)
    usage = result.usage

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
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(usage.cost_usd, 6),
            llm_calls=usage.llm_calls,
            tool_calls=usage.tool_calls,
            models_used=list(usage.models_used),
            duration_ms=duration_ms,
        ),
        error=result.error,
    )


@router.post("/agents/{agent_id}/invoke", response_model=InvokeResponse)
async def invoke_agent(
    body: InvokeRequest,
    request: Request,
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> InvokeResponse | JSONResponse:
    """Invoke an agent with a message."""
    gw: Gateway = request.app

    snapshot = gw._snapshot
    if snapshot is None or snapshot.workspace is None:
        return error_response(503, "workspace_unavailable", "Workspace not loaded")

    # Look up agent
    agent = snapshot.workspace.agents.get(agent_id)
    if agent is None:
        return error_response(404, "agent_not_found", f"Agent '{agent_id}' not found")

    if snapshot.engine is None:
        return error_response(503, "engine_unavailable", "Execution engine not initialized")

    # Generate execution ID
    execution_id = str(uuid.uuid4())

    # Build execution options
    exec_options = ExecutionOptions(
        async_execution=body.options.async_,
        timeout_ms=body.options.timeout_ms,
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
        if gw._execution_semaphore.locked():
            return error_response(429, "too_many_requests", "Too many concurrent executions")

        handle = ExecutionHandle(execution_id)
        gw._execution_handles[execution_id] = handle
        task = asyncio.create_task(
            _run_background_execution(gw, agent, body, execution_id, exec_options, handle),
            name=f"exec-{execution_id}",
        )
        gw._background_tasks.add(task)
        task.add_done_callback(gw._background_tasks.discard)

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
        result = await snapshot.engine.execute(
            agent=agent,
            message=body.message,
            workspace=snapshot.workspace,
            context=body.context,
            options=exec_options,
            handle=handle,
            tool_executor=execute_tool,
        )
    except Exception as e:
        logger.error("Execution failed: %s", e)
        await gw._execution_repo.update_status(execution_id, ExecutionStatus.FAILED, error=str(e))
        return error_response(
            500, "execution_error", "Internal execution error", execution_id=execution_id
        )
    finally:
        gw._execution_handles.pop(execution_id, None)

    duration_ms = int((time.monotonic() - start) * 1000)

    # Persist result
    status = stop_reason_to_status(result.stop_reason)
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
    async with gw._execution_semaphore:
        try:
            snapshot = gw._snapshot
            if snapshot is None or snapshot.engine is None:
                raise RuntimeError("Gateway not initialized")

            await gw._execution_repo.update_status(execution_id, ExecutionStatus.RUNNING)

            result = await snapshot.engine.execute(
                agent=agent,
                message=body.message,
                workspace=snapshot.workspace,
                context=body.context,
                options=options,
                handle=handle,
                tool_executor=execute_tool,
            )

            status = stop_reason_to_status(result.stop_reason)
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
