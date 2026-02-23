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
from agent_gateway.api.openapi import build_responses
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
    summary="Chat with an agent",
    description=(
        "Send a message in a multi-turn conversation. "
        "Creates a new session or continues an existing one."
    ),
    tags=["Chat"],
    responses={
        200: {"model": ChatResponse, "description": "Successful non-streaming chat response."},
        **build_responses(auth=True, not_found=True, rate_limit=True),
    },
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
    auth = request.scope.get("auth")
    try:
        session_id, result = await gw.chat(
            agent_id=agent_id,
            message=body.message,
            session_id=body.session_id,
            input=body.input or None,
            options=ExecutionOptions(timeout_ms=body.options.timeout_ms),
            auth=auth,
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

        retriever_reg = snapshot.retriever_registry
        system_prompt = await assemble_system_prompt(
            agent,
            snapshot.workspace,
            query=body.message,
            retriever_registry=retriever_reg,
            context_retrieval_config=snapshot.context_retrieval_config,
            chat_mode=True,
        )
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
    summary="Get session details",
    description="Retrieve details of a specific chat session.",
    tags=["Sessions"],
    responses=build_responses(auth=True, not_found=True),
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

    # Enforce session ownership
    auth = request.scope.get("auth")
    user_id = gw._derive_user_id(auth) if auth else None
    if user_id is not None and session.user_id is not None and session.user_id != user_id:
        return error_response(403, "forbidden", "Not authorized to access this session")

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
    summary="Delete a session",
    description="Delete a chat session and its history.",
    tags=["Sessions"],
    responses=build_responses(auth=True, not_found=True),
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

    # Check ownership before deleting
    session = gw._session_store.get_session(session_id)
    if session is None:
        return error_response(404, "session_not_found", f"Session '{session_id}' not found")

    auth = request.scope.get("auth")
    user_id = gw._derive_user_id(auth) if auth else None
    if user_id is not None and session.user_id is not None and session.user_id != user_id:
        return error_response(403, "forbidden", "Not authorized to delete this session")

    gw._session_store.delete_session(session_id)
    return JSONResponse(status_code=200, content={"deleted": True})


@router.get(
    "/sessions",
    summary="List sessions",
    description=(
        "List active chat sessions. In multi-user mode, only returns the caller's sessions."
    ),
    tags=["Sessions"],
    responses=build_responses(auth=True),
    dependencies=[Depends(RequireScope("sessions:read"))],
)
async def list_sessions(
    request: Request,
    agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[SessionInfo]:
    """List active sessions. In multi-user mode, only returns the caller's sessions."""
    gw: Gateway = request.app

    if gw._session_store is None:
        return []

    auth = request.scope.get("auth")
    user_id = gw._derive_user_id(auth) if auth else None

    sessions = gw._session_store.list_sessions(agent_id=agent_id, user_id=user_id, limit=limit)
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


# --- Conversation history endpoints (persistent) ---


@router.get(
    "/users/me/conversations",
    response_model=None,
    summary="List conversations",
    description="List the caller's persisted conversations.",
    tags=["Conversations"],
    responses=build_responses(auth=True),
    dependencies=[Depends(RequireScope("sessions:read"))],
)
async def list_conversations(
    request: Request,
    agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List the caller's persisted conversations."""
    gw: Gateway = request.app
    auth = request.scope.get("auth")
    user_id = gw._derive_user_id(auth) if auth else None

    if user_id is None:
        return error_response(  # type: ignore[return-value]
            401, "auth_required", "Authentication required to list conversations"
        )

    records = await gw._conversation_repo.list_by_user(
        user_id=user_id, agent_id=agent_id, limit=limit, offset=offset
    )
    return [
        {
            "conversation_id": r.conversation_id,
            "agent_id": r.agent_id,
            "title": r.title,
            "summary": r.summary,
            "message_count": r.message_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in records
    ]


@router.get(
    "/users/me/conversations/{conversation_id}/messages",
    response_model=None,
    summary="Get conversation messages",
    description="Retrieve messages from a persisted conversation.",
    tags=["Conversations"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("sessions:read"))],
)
async def get_conversation_messages(
    request: Request,
    conversation_id: str = Path(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]] | JSONResponse:
    """Get messages from a persisted conversation."""
    gw: Gateway = request.app
    auth = request.scope.get("auth")
    user_id = gw._derive_user_id(auth) if auth else None

    if user_id is None:
        return error_response(401, "auth_required", "Authentication required")

    # Verify conversation ownership
    record = await gw._conversation_repo.get(conversation_id)
    if record is None:
        return error_response(404, "not_found", "Conversation not found")
    if record.user_id != user_id:
        return error_response(403, "forbidden", "Not authorized to access this conversation")

    messages = await gw._conversation_repo.get_messages(
        conversation_id, limit=limit, offset=offset
    )
    return [
        {
            "message_id": m.message_id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


# --- Memory management endpoints ---


@router.post(
    "/agents/{agent_id}/memory/compact",
    summary="Compact agent memory",
    description="Trigger memory compaction for an agent. Administrative operation.",
    tags=["Admin"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("agents:manage"))],
)
async def compact_agent_memory(
    request: Request,
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> JSONResponse:
    """Trigger memory compaction for an agent. Admin operation."""
    gw: Gateway = request.app

    if gw.memory_manager is None:
        return error_response(503, "memory_unavailable", "Memory system not enabled")

    auth = request.scope.get("auth")
    user_id = gw._derive_user_id(auth) if auth else None

    # Compact global agent memory
    global_compacted = await gw.memory_manager.compact_memories(agent_id, user_id=None)

    # Compact per-user memory if authenticated
    user_compacted = 0
    if user_id is not None:
        user_compacted = await gw.memory_manager.compact_memories(agent_id, user_id=user_id)

    return JSONResponse(
        status_code=200,
        content={
            "agent_id": agent_id,
            "global_compacted": global_compacted,
            "user_compacted": user_compacted,
        },
    )
