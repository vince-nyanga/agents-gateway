"""Multi-turn chat endpoint and session management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Path, Query, Request
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
from agent_gateway.api.routes.status import stop_reason_to_status
from agent_gateway.auth.scopes import RequireScope
from agent_gateway.engine.models import ExecutionHandle, ExecutionOptions

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)


@router.post(
    "/agents/{agent_id}/chat",
    response_model=None,
    dependencies=[Depends(RequireScope("agents:invoke"))],
)
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

    # Handle streaming — the streaming generator acquires its own lock
    if body.options.stream:
        return _create_streaming_response(
            gw=gw,
            agent_id=agent_id,
            body=body,
        )

    # Non-streaming: delegate to gw.chat()
    try:
        session_id, result = await gw.chat(
            agent_id=agent_id,
            message=body.message,
            session_id=body.session_id,
            input=body.input or None,
            options=ExecutionOptions(timeout_ms=body.options.timeout_ms),
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg and "Session" in msg:
            return error_response(404, "session_not_found", msg)
        if "not found" in msg and "Agent" in msg:
            return error_response(404, "agent_not_found", msg)
        if "mismatch" in msg or "belongs to agent" in msg:
            return error_response(409, "session_agent_mismatch", msg)
        return error_response(500, "execution_error", msg)
    except Exception as e:
        logger.error("Chat execution failed: %s", e)
        return error_response(500, "execution_error", "Internal execution error")

    status = stop_reason_to_status(result.stop_reason)
    usage = result.usage

    # Get turn count from session
    session = gw._session_store.get_session(session_id) if gw._session_store else None
    turn_count = session.turn_count if session else 0

    return ChatResponse(
        session_id=session_id,
        execution_id="",
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
            duration_ms=result.duration_ms,
        ),
        error=result.error,
        turn_count=turn_count,
    )


def _create_streaming_response(
    gw: Gateway,
    agent_id: str,
    body: ChatRequest,
) -> StreamingResponse:
    """Create an SSE streaming response for a chat message."""
    from agent_gateway.engine.streaming import stream_chat_execution
    from agent_gateway.workspace.prompt import assemble_system_prompt

    async def event_generator() -> Any:
        snapshot = gw._snapshot
        if snapshot is None or snapshot.workspace is None:
            return

        agent = snapshot.workspace.agents.get(agent_id)
        if agent is None:
            return

        session_store = gw._session_store
        if session_store is None:
            return

        # Get or create session
        if body.session_id:
            session = session_store.get_session(body.session_id)
            if session is None:
                return
            if session.agent_id != agent_id:
                return
        else:
            session = session_store.create_session(agent_id, metadata=body.input or None)

        if body.input:
            session.metadata.update(body.input)

        # Append user message and build messages (inside generator, before lock)
        session.append_user_message(body.message)
        session.truncate_history(session_store._max_history)

        system_prompt = assemble_system_prompt(agent, snapshot.workspace)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *session.messages,
        ]

        exec_options = ExecutionOptions(timeout_ms=body.options.timeout_ms)
        import uuid

        execution_id = str(uuid.uuid4())
        handle = ExecutionHandle(execution_id)
        gw._execution_handles[execution_id] = handle

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


@router.get(
    "/sessions/{session_id}",
    response_model=SessionInfo,
    dependencies=[Depends(RequireScope("sessions:read"))],
)
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


@router.delete(
    "/sessions/{session_id}",
    dependencies=[Depends(RequireScope("sessions:manage"))],
)
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


@router.get("/sessions", dependencies=[Depends(RequireScope("sessions:read"))])
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
