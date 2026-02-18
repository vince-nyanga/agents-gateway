---
title: "Phase 1.8b: Multi-Turn Chat Endpoint with SSE Streaming"
type: feat
status: completed
date: 2026-02-18
depends_on: [08]
blocks: []
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.8b: Multi-Turn Chat Endpoint with SSE Streaming

## Goal

Add a multi-turn conversational endpoint (`POST /v1/agents/{agent_id}/chat`) that maintains server-side session state and supports optional SSE streaming. This complements the existing single-shot `/invoke` endpoint.

## Prerequisites

- Phase 08 (API Layer & Gateway Class) complete

---

## Design

### Session Model

Each chat session has:
- **session_id**: Unique identifier (UUID)
- **agent_id**: The agent this session belongs to
- **messages**: Accumulated conversation history (list of `{role, content}` dicts)
- **created_at**: When the session started
- **updated_at**: Last message timestamp
- **metadata**: Optional context dict

Sessions are stored in-memory by default (single-process). Optional persistence to DB for session recovery across restarts.

### API Endpoints

```
POST   /v1/agents/{agent_id}/chat          # Send a message (creates session if none provided)
GET    /v1/sessions/{session_id}            # Get session details + message history
DELETE /v1/sessions/{session_id}            # End/delete a session
GET    /v1/sessions?agent_id={id}&limit=50  # List sessions
```

### Request/Response

**POST /v1/agents/{agent_id}/chat**

Request:
```json
{
  "message": "What is 2 + 3?",
  "session_id": "sess_abc123",     // Optional: omit to create new session
  "context": {},                    // Optional: merged into session context
  "options": {
    "stream": false,                // Set true for SSE streaming
    "timeout_ms": 60000
  }
}
```

Response (non-streaming):
```json
{
  "session_id": "sess_abc123",
  "execution_id": "exec_xyz",
  "agent_id": "assistant",
  "status": "completed",
  "result": {
    "output": null,
    "raw_text": "2 + 3 = 5",
    "validation_errors": null
  },
  "usage": {
    "input_tokens": 150,
    "output_tokens": 20,
    "cost_usd": 0.001,
    "duration_ms": 1200
  },
  "turn_count": 3
}
```

Response (streaming, `options.stream: true`):
```
event: session
data: {"session_id": "sess_abc123", "execution_id": "exec_xyz"}

event: token
data: {"content": "2 + "}

event: token
data: {"content": "3 = "}

event: token
data: {"content": "5"}

event: tool_call
data: {"name": "add-numbers", "arguments": {"a": 2, "b": 3}, "call_id": "c1"}

event: tool_result
data: {"call_id": "c1", "name": "add-numbers", "output": {"result": 5}}

event: done
data: {"status": "completed", "usage": {...}, "turn_count": 3}

event: ping
data: {}
```

### Execution Flow

1. Client sends message + optional `session_id`
2. If no `session_id`, create new session → assign UUID
3. Append user message to session history
4. Build messages array: system prompt + full session history
5. Run execution engine with full message history
6. Append assistant response to session history
7. Return response (or stream tokens via SSE)
8. Session stays alive for subsequent turns

### Session Management

- **In-memory storage**: `dict[str, ChatSession]` on the Gateway instance
- **TTL**: Sessions expire after configurable idle time (default 30 minutes)
- **Max sessions**: Configurable limit (default 1000) with LRU eviction
- **Max history**: Configurable max messages per session (default 100) — oldest messages truncated
- **Cleanup**: Background task runs every 60s to evict expired sessions

### SSE Streaming

- Use `StreamingResponse` with `text/event-stream` content type
- Event types: `session`, `token`, `tool_call`, `tool_result`, `error`, `done`, `ping`
- Heartbeat: `event: ping` every 15s
- Triggered by `options.stream: true` in request body
- Tokens streamed via `litellm.acompletion(stream=True)` which yields deltas
- Tool calls and results emitted as discrete events between token streams
- `done` event includes final usage stats and validated output

### Robustness

- Session not found → 404 with clear message
- Session for different agent → 409 conflict
- Concurrent messages to same session → serialize via per-session `asyncio.Lock`
- LLM failure mid-conversation → error event (streaming) or error response, session preserved
- Session history too large for context window → truncate oldest messages with notice

---

## Tasks

### 1. Session Model and Store

**File:** `src/agent_gateway/chat/session.py`

- [x] `ChatSession` dataclass: `session_id`, `agent_id`, `messages`, `created_at`, `updated_at`, `metadata`, `lock`
- [x] `SessionStore` class: in-memory dict with TTL, max sessions, LRU eviction
- [x] `create_session()`, `get_session()`, `delete_session()`, `list_sessions()`, `cleanup_expired()`
- [x] Per-session `asyncio.Lock` for serializing concurrent requests

### 2. Chat Request/Response Models

**File:** `src/agent_gateway/api/models.py` (extend existing)

- [x] `ChatRequest` — message, session_id (optional), context, options
- [x] `ChatResponse` — session_id, execution_id, agent_id, status, result, usage, turn_count
- [x] `SessionInfo` — session_id, agent_id, turn_count, created_at, updated_at

### 3. Chat Endpoint

**File:** `src/agent_gateway/api/routes/chat.py`

- [x] `POST /v1/agents/{agent_id}/chat` — main chat endpoint
- [x] Non-streaming: run engine with full history, return response
- [x] Streaming: return SSE `StreamingResponse`
- [x] Create session if `session_id` not provided
- [x] Validate session belongs to correct agent
- [x] Serialize concurrent requests to same session

### 4. Session Management Endpoints

**File:** `src/agent_gateway/api/routes/chat.py` (same file)

- [x] `GET /v1/sessions/{session_id}` — session details + message count
- [x] `DELETE /v1/sessions/{session_id}` — end session
- [x] `GET /v1/sessions` — list sessions (with agent_id filter)

### 5. SSE Streaming Support

**File:** `src/agent_gateway/engine/streaming.py`

- [x] Streaming execution wrapper that yields SSE events
- [x] Token streaming via `litellm.acompletion(stream=True)`
- [x] Heartbeat coroutine (ping every 15s)
- [x] Event formatting: `event: {type}\ndata: {json}\n\n`

### 6. LLM Client Streaming

**File:** `src/agent_gateway/engine/llm.py` (extend existing)

- [x] Add `stream_completion()` method that yields token chunks
- [x] Handle streaming + tool calls (LiteLLM handles this)

### 7. Gateway Wiring

**File:** `src/agent_gateway/gateway.py` (extend existing)

- [x] Initialize `SessionStore` during startup
- [x] Register chat routes in `/v1/` router
- [x] Start session cleanup background task
- [x] Stop cleanup task on shutdown
- [x] `gw.chat()` programmatic method

### 8. Tests

- [x] Unit tests for `SessionStore` (create, get, delete, TTL, max sessions, LRU)
- [x] Unit tests for `ChatSession` (message appending, lock serialization)
- [x] Integration test: multi-turn conversation (3+ turns)
- [x] Integration test: SSE streaming event sequence
- [x] Integration test: session CRUD endpoints
- [x] Integration test: concurrent messages to same session
- [x] Integration test: session expiry
- [x] Integration test: session for wrong agent → 409

---

## Acceptance Criteria

- [x] `POST /v1/agents/{id}/chat` creates a session and returns a response
- [x] Subsequent messages with the same `session_id` continue the conversation
- [x] `options.stream: true` returns SSE event stream
- [x] Session CRUD endpoints work (get, list, delete)
- [x] Sessions expire after TTL
- [x] Concurrent messages to same session are serialized
- [x] LLM sees full conversation history on each turn
- [x] Tool calls work within multi-turn context
- [x] All tests pass
