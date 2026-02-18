---
title: "Phase 1.8: API Layer & Gateway Class"
type: feat
status: completed
date: 2026-02-18
depends_on: [01, 02, 03, 04, 05, 06, 07]
blocks: [09, 10, 11, 12]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.8: API Layer & Gateway Class (Integration)

## Goal

Wire everything together. Complete the `Gateway` class with lifespan management, auto-generated routes, and all dependencies connected. After this phase, `python app.py` starts a working server that can invoke agents end-to-end.

## Prerequisites

- All Phase 1 sub-plans (01-07) complete

---

## Tasks

### 1. Complete Gateway Class

**File:** `src/agent_gateway/gateway.py`

Full implementation:

- **Lifespan composition**: Wrap user's lifespan with gateway's using nested `@asynccontextmanager`. Gateway startup: load workspace → init DB → setup telemetry → start watcher (if reload) → register tools → register routes. Gateway shutdown: stop watcher → dispose DB engine.
- **Separate kwargs**: Gateway-specific (`workspace`, `auth`, `reload`) extracted before passing rest to `FastAPI.__init__()`.
- **Tool registration**: `_pending_tools` from `@gw.tool()` calls merged into `ToolRegistry` at startup.
- **Event hooks**: `@gw.on(event_name)` stores handlers, dispatched during execution.
- **Programmatic invocation**: `gw.invoke(agent_id, message, context)` bypasses HTTP, calls executor directly.
- **Graceful degradation**: Workspace load failure → empty workspace with health errors. DB failure → NullPersistence. Telemetry failure → warning only.
- **State**: `self._workspace`, `self._tool_registry`, `self._llm_client`, `self._db_session_factory`, `self._persistence`, `self._metrics`.

### 2. Request/Response Models

**File:** `src/agent_gateway/api/models.py`

Pydantic models for API request/response:

```python
class InvokeRequest(BaseModel):
    message: str = Field(..., max_length=102_400)  # 100KB max
    context: dict[str, Any] = Field(default_factory=dict)
    options: InvokeOptions = InvokeOptions()

class InvokeOptions(BaseModel):
    async_: bool = Field(False, alias="async")
    timeout_ms: int | None = None
    callback_url: str | None = None
    notify: list[str] = Field(default_factory=list)
    stream: bool = False

class InvokeResponse(BaseModel):
    execution_id: str
    agent_id: str
    status: str
    result: ResultPayload | None = None
    usage: UsagePayload | None = None

class ResultPayload(BaseModel):
    output: dict[str, Any] | None = None
    raw_text: str = ""
    validation_errors: list[str] | None = None

class UsagePayload(BaseModel):
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    duration_ms: int = 0

class ErrorResponse(BaseModel):
    error: ErrorDetail

class ErrorDetail(BaseModel):
    code: str
    message: str
    execution_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
```

### 3. Agent Route (Invoke Endpoint)

**File:** `src/agent_gateway/api/routes/invoke.py`

`POST /v1/agents/{agent_id}/invoke`

Flow:
1. Validate request body
2. Look up agent in workspace state → 404 if not found
3. Resolve agent's tools (from skills + direct tools) via registry
4. Generate execution_id
5. Create execution record in DB (status: running)
6. If `options.async`: start background task, return 202 with execution_id
7. If `options.stream`: return SSE StreamingResponse (Phase 11)
8. Else: run executor synchronously, return result
9. Fire notifications (Phase 10)
10. Update execution record with result

### 4. Executions Routes

**File:** `src/agent_gateway/api/routes/executions.py`

- `GET /v1/executions/{execution_id}` — get execution result/status
- `GET /v1/executions?agent_id=X&limit=50` — list executions
- `POST /v1/executions/{execution_id}/cancel` — cancel running execution

### 5. Introspection Routes

**File:** `src/agent_gateway/api/routes/introspection.py`

- `GET /v1/agents` — list all agents (id, description, skills, tools)
- `GET /v1/agents/{agent_id}` — agent details
- `GET /v1/skills` — list all skills
- `GET /v1/skills/{skill_id}` — skill details
- `GET /v1/tools` — list all tools (file + code)
- `GET /v1/tools/{tool_id}` — tool details
- `POST /v1/reload` — re-scan workspace

### 6. Health Route

**File:** `src/agent_gateway/api/routes/health.py`

- `GET /v1/health` — returns status, startup errors, agent count, workspace path

### 7. Custom APIRoute Subclass

**File:** `src/agent_gateway/api/routes/base.py`

Custom `APIRoute` for agent endpoints:
- Auto-inject `execution_id` into `request.state`
- Inject trace context
- Record execution metrics (duration)
- Add `X-Execution-Id` response header

Apply only to `/v1/` routes, not user custom routes.

### 8. Route Registration

In Gateway lifespan:
- Create `APIRouter(prefix="/v1")` with custom route class
- Register invoke, executions, introspection, health routes
- `self.include_router(agent_router)`

---

## Integration Tests

**`tests/test_integration/test_full_flow.py`:**

Using `TestClient(gw)`:

1. Create Gateway with fixture workspace
2. Register `@gw.tool` echo tool
3. Mock LiteLLM to return tool call → tool result → text response
4. `POST /v1/agents/test-agent/invoke` → verify full response
5. Verify execution stored in DB
6. `GET /v1/executions/{id}` → verify result
7. `GET /v1/agents` → verify agent listed
8. `GET /v1/health` → verify ok

**`tests/test_integration/test_error_handling.py`:**

- Unknown agent → 404
- Empty message → 422
- Tool crash during execution → execution completes with tool error in results
- LLM failure → execution failed

**`tests/test_integration/test_programmatic.py`:**

- `gw.invoke("test-agent", "hello")` works without HTTP

## Acceptance Criteria

- [ ] `python app.py` starts server and serves agent endpoints
- [ ] `POST /v1/agents/{id}/invoke` executes agent and returns result
- [ ] Execution history stored and queryable
- [ ] Introspection endpoints list agents/skills/tools
- [ ] Health endpoint reports status
- [ ] Graceful degradation: starts even with workspace errors
- [ ] `gw.invoke()` programmatic invocation works
- [ ] Error responses use standard envelope
- [ ] All integration tests pass
- [ ] Test project (`examples/test-project`) runs end-to-end
