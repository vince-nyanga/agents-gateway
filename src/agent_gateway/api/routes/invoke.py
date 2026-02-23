"""Agent invocation endpoint."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response
from agent_gateway.api.models import (
    InvokeRequest,
    InvokeResponse,
    ResultPayload,
    UsagePayload,
)
from agent_gateway.api.openapi import build_responses
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.api.routes.status import stop_reason_to_status
from agent_gateway.auth.scopes import RequireScope
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
    ExecutionStatus,
)
from agent_gateway.persistence.domain import ExecutionRecord
from agent_gateway.queue.models import ExecutionJob
from agent_gateway.queue.null import NullQueue
from agent_gateway.telemetry.metrics import create_metrics
from agent_gateway.tools.runner import execute_tool

_metrics = create_metrics()

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway
    from agent_gateway.workspace.agent import AgentDefinition

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)


def _should_queue(agent: AgentDefinition, request_async: bool) -> bool:
    """Determine whether an invocation should be queued.

    Agent config is a floor, not a ceiling:
    - ``execution_mode: async`` forces queuing regardless of request.
    - ``execution_mode: sync`` allows the client to opt into async.
    """
    if agent.execution_mode == "async":
        return True
    return request_async


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


@router.post(
    "/agents/{agent_id}/invoke",
    response_model=InvokeResponse,
    summary="Invoke an agent",
    description=(
        "Send a message to an agent and receive a response. "
        "Supports synchronous, asynchronous (polling), and streaming modes."
    ),
    tags=["Agents"],
    responses={
        202: {
            "description": "Accepted — async execution queued. Poll via the returned URL.",
        },
        **build_responses(auth=True, not_found=True, rate_limit=True),
    },
    dependencies=[Depends(RequireScope("agents:invoke"))],
)
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

    # Validate input against agent's input_schema (before creating execution record)
    if agent.input_schema:
        from agent_gateway.engine.input import validate_input

        errors = validate_input(body.input, agent.input_schema)
        if errors:
            return error_response(
                422,
                "input_validation_failed",
                f"Input validation failed: {'; '.join(errors)}",
            )

    # Generate execution ID
    execution_id = str(uuid.uuid4())

    # Determine execution mode
    should_queue = _should_queue(agent, body.options.async_)

    # Guard: streaming + async are incompatible
    if should_queue and body.options.stream:
        return error_response(
            400,
            "streaming_not_supported",
            "Streaming is not available for async agents. Use polling or callbacks.",
        )

    # Build execution options
    exec_options = ExecutionOptions(
        async_execution=should_queue,
        timeout_ms=body.options.timeout_ms,
        stream=body.options.stream,
        output_schema=body.options.output_schema,
    )

    # Create execution record
    initial_status = ExecutionStatus.QUEUED if should_queue else ExecutionStatus.RUNNING
    record = ExecutionRecord(
        id=execution_id,
        agent_id=agent_id,
        status=initial_status,
        message=body.message,
        input=body.input or None,
        started_at=datetime.now(UTC),
    )
    await gw._execution_repo.create(record)

    # Queued execution: enqueue to backend, return 202
    if should_queue:
        if isinstance(gw._queue, NullQueue):
            # No queue configured — fall back to asyncio.create_task
            handle = ExecutionHandle(execution_id)
            gw._execution_handles[execution_id] = handle
            task = asyncio.create_task(
                _run_background_execution(gw, agent, body, execution_id, exec_options, handle),
                name=f"exec-{execution_id}",
            )
            gw._background_tasks.add(task)
            task.add_done_callback(gw._background_tasks.discard)
        else:
            job = ExecutionJob(
                execution_id=execution_id,
                agent_id=agent_id,
                message=body.message,
                input=body.input or None,
                timeout_ms=body.options.timeout_ms,
                enqueued_at=datetime.now(UTC).isoformat(),
            )
            await gw._queue.enqueue(job)
            _metrics.queue_jobs_enqueued.add(1, {"agent_id": agent_id})
            _metrics.queue_depth.add(1, {"agent_id": agent_id})

        return JSONResponse(
            status_code=202,
            content={
                "execution_id": execution_id,
                "agent_id": agent_id,
                "status": "queued",
                "poll_url": f"/v1/executions/{execution_id}",
            },
        )

    # Synchronous execution
    handle = ExecutionHandle(execution_id)
    gw._execution_handles[execution_id] = handle
    start = time.monotonic()

    # Load per-user agent config for personal agents
    auth = request.scope.get("auth")
    user_id = gw._derive_user_id(auth) if auth else None
    user_instructions: str | None = None
    user_secrets: dict[str, str] = {}
    user_config_values: dict[str, Any] = {}

    if agent.scope == "personal":
        if not user_id:
            return error_response(
                401,
                "auth_required",
                f"Agent '{agent_id}' is a personal agent and requires authentication",
            )
        user_agent_config = await gw._user_agent_config_repo.get(user_id, agent_id)
        if user_agent_config is None or not user_agent_config.setup_completed:
            return error_response(
                409,
                "setup_required",
                f"Agent '{agent_id}' requires setup. "
                f"Configure via POST /v1/agents/{agent_id}/config",
            )
        user_instructions = user_agent_config.instructions
        user_config_values = user_agent_config.config_values
        user_secrets = gw._decrypt_user_secrets(user_agent_config.encrypted_secrets)

    try:
        result = await snapshot.engine.execute(
            agent=agent,
            message=body.message,
            workspace=snapshot.workspace,
            input=body.input,
            options=exec_options,
            handle=handle,
            tool_executor=execute_tool,
            caller_identity=user_id,
            user_instructions=user_instructions,
            user_secrets=user_secrets,
            user_config=user_config_values,
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

    # Fire notifications
    gw.fire_notifications(
        execution_id=execution_id,
        agent_id=agent_id,
        status=result.stop_reason.value,
        message=body.message,
        config=agent.notifications,
        result=result.to_dict() if result.raw_text else None,
        usage=result.usage.to_dict() if result.usage else None,
        duration_ms=duration_ms,
        input=body.input or None,
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
    assert gw._execution_semaphore is not None
    async with gw._execution_semaphore:
        try:
            snapshot = gw._snapshot
            if snapshot is None or snapshot.engine is None:
                raise RuntimeError("Gateway not initialized")

            await gw._execution_repo.update_status(execution_id, ExecutionStatus.RUNNING)

            start = time.monotonic()
            result = await snapshot.engine.execute(
                agent=agent,
                message=body.message,
                workspace=snapshot.workspace,
                input=body.input,
                options=options,
                handle=handle,
                tool_executor=execute_tool,
            )
            bg_duration_ms = int((time.monotonic() - start) * 1000)

            status = stop_reason_to_status(result.stop_reason)
            await gw._execution_repo.update_status(
                execution_id, status, completed_at=datetime.now(UTC)
            )
            await gw._execution_repo.update_result(
                execution_id,
                result=result.to_dict(),
                usage=result.usage.to_dict(),
            )

            # Fire notifications
            gw.fire_notifications(
                execution_id=execution_id,
                agent_id=agent.id,
                status=result.stop_reason.value,
                message=body.message,
                config=agent.notifications,
                result=result.to_dict() if result.raw_text else None,
                usage=result.usage.to_dict() if result.usage else None,
                duration_ms=bg_duration_ms,
                input=body.input or None,
            )
        except Exception as e:
            logger.error("Background execution %s failed: %s", execution_id, e)
            await gw._execution_repo.update_status(
                execution_id, ExecutionStatus.FAILED, error=str(e)
            )
        finally:
            gw._execution_handles.pop(execution_id, None)
