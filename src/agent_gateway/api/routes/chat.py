"""Multi-turn chat endpoint and session management."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent_gateway.api.errors import error_response
from agent_gateway.api.models import (
    ChatRequest,
    ChatResponse,
    ResultPayload,
    SessionInfo,
    UsagePayload,
)
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    StopReason,
)
from agent_gateway.tools.runner import execute_tool
from agent_gateway.workspace.prompt import assemble_system_prompt

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)


def _stop_reason_to_status(stop_reason: StopReason) -> str:
    """Map engine StopReason to API status string."""
    from agent_gateway.engine.models import ExecutionStatus

    mapping = {
        StopReason.COMPLETED: ExecutionStatus.COMPLETED,
        StopReason.MAX_ITERATIONS: ExecutionStatus.COMPLETED,
        StopReason.MAX_TOOL_CALLS: ExecutionStatus.COMPLETED,
        StopReason.TIMEOUT: ExecutionStatus.TIMEOUT,
        StopReason.CANCELLED: ExecutionStatus.CANCELLED,
        StopReason.ERROR: ExecutionStatus.FAILED,
    }
    return mapping.get(stop_reason, ExecutionStatus.FAILED)


@router.post("/agents/{agent_id}/chat", response_model=None)
async def chat_with_agent(
    body: ChatRequest,
    request: Request,
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> ChatResponse | JSONResponse | StreamingResponse:
    """Send a message to an agent in a multi-turn conversation."""
    gw: Gateway = request.app

    snapshot = gw._snapshot
    if snapshot is None or snapshot.workspace is None:
        return error_response(503, "workspace_unavailable", "Workspace not loaded")

    agent = snapshot.workspace.agents.get(agent_id)
    if agent is None:
        return error_response(404, "agent_not_found", f"Agent '{agent_id}' not found")

    if snapshot.engine is None:
        return error_response(503, "engine_unavailable", "Execution engine not initialized")

    if gw._session_store is None:
        return error_response(503, "sessions_unavailable", "Session store not initialized")

    session_store = gw._session_store

    # Get or create session
    if body.session_id:
        session = session_store.get_session(body.session_id)
        if session is None:
            return error_response(
                404, "session_not_found", f"Session '{body.session_id}' not found"
            )
        if session.agent_id != agent_id:
            return error_response(
                409,
                "session_agent_mismatch",
                f"Session '{body.session_id}' belongs to agent "
                f"'{session.agent_id}', not '{agent_id}'",
            )
    else:
        session = session_store.create_session(agent_id, metadata=body.context or None)

    # Merge context
    if body.context:
        session.metadata.update(body.context)

    # Serialize concurrent requests to same session
    async with session.lock:
        # Append user message
        session.append_user_message(body.message)

        # Truncate history if needed
        session.truncate_history(session_store._max_history)

        # Build system prompt
        system_prompt = assemble_system_prompt(agent, snapshot.workspace)

        # Build full message history for engine
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *session.messages,
        ]

        # Build execution options
        exec_options = ExecutionOptions(
            timeout_ms=body.options.timeout_ms,
        )

        execution_id = str(uuid.uuid4())
        handle = ExecutionHandle(execution_id)
        gw._execution_handles[execution_id] = handle

        # Handle streaming
        if body.options.stream:
            return _create_streaming_response(
                gw=gw,
                agent=agent,
                session=session,
                messages=messages,
                exec_options=exec_options,
                execution_id=execution_id,
                handle=handle,
            )

        # Non-streaming execution
        start = time.monotonic()
        try:
            result = await snapshot.engine.execute(
                agent=agent,
                message=body.message,
                workspace=snapshot.workspace,
                context=session.metadata,
                options=exec_options,
                handle=handle,
                tool_executor=execute_tool,
                message_history=messages,
            )
        except Exception as e:
            logger.error("Chat execution failed: %s", e)
            return error_response(
                500, "execution_error", "Internal execution error", execution_id=execution_id
            )
        finally:
            gw._execution_handles.pop(execution_id, None)

        duration_ms = int((time.monotonic() - start) * 1000)

        # Append assistant response to session
        if result.raw_text:
            session.append_assistant_message(content=result.raw_text)

        status = _stop_reason_to_status(result.stop_reason)
        usage = result.usage

        return ChatResponse(
            session_id=session.session_id,
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
            turn_count=session.turn_count,
        )


def _create_streaming_response(
    gw: Any,
    agent: Any,
    session: Any,
    messages: list[dict[str, Any]],
    exec_options: ExecutionOptions,
    execution_id: str,
    handle: ExecutionHandle,
) -> StreamingResponse:
    """Create an SSE streaming response for a chat message."""
    from agent_gateway.engine.streaming import stream_chat_execution

    async def event_generator() -> Any:
        try:
            async for event in stream_chat_execution(
                gw=gw,
                agent=agent,
                session=session,
                messages=messages,
                exec_options=exec_options,
                execution_id=execution_id,
                handle=handle,
            ):
                yield event
        finally:
            gw._execution_handles.pop(execution_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Session CRUD endpoints ---


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(
    request: Request,
    session_id: str = Path(..., min_length=1),
) -> SessionInfo | JSONResponse:
    """Get session details."""
    gw: Gateway = request.app

    if gw._session_store is None:
        return error_response(503, "sessions_unavailable", "Session store not initialized")

    session = gw._session_store.get_session(session_id)
    if session is None:
        return error_response(404, "session_not_found", f"Session '{session_id}' not found")

    return SessionInfo(
        session_id=session.session_id,
        agent_id=session.agent_id,
        turn_count=session.turn_count,
        message_count=len(session.messages),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    request: Request,
    session_id: str = Path(..., min_length=1),
) -> JSONResponse:
    """Delete a session."""
    gw: Gateway = request.app

    if gw._session_store is None:
        return error_response(503, "sessions_unavailable", "Session store not initialized")

    deleted = gw._session_store.delete_session(session_id)
    if not deleted:
        return error_response(404, "session_not_found", f"Session '{session_id}' not found")

    return JSONResponse(status_code=200, content={"deleted": True})


@router.get("/sessions")
async def list_sessions(
    request: Request,
    agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[SessionInfo]:
    """List active sessions."""
    gw: Gateway = request.app

    if gw._session_store is None:
        return []

    sessions = gw._session_store.list_sessions(agent_id=agent_id, limit=limit)
    return [
        SessionInfo(
            session_id=s.session_id,
            agent_id=s.agent_id,
            turn_count=s.turn_count,
            message_count=len(s.messages),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]
