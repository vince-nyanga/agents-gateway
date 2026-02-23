# Gateway Class

`Gateway` is the central class of Agent Gateway. It subclasses `FastAPI` directly, so every FastAPI feature — dependency injection, middleware, custom routes, OpenAPI generation — works unchanged. Agents, skills, and tools are defined as markdown files in a workspace directory and loaded at startup.

```python
from agent_gateway import Gateway
```

---

## Constructor

```python
Gateway(
    workspace: str | Path = "./workspace",
    auth: bool | Callable | AuthProvider = True,
    reload: bool = False,
    **fastapi_kwargs,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `workspace` | `str \| Path` | `"./workspace"` | Path to the workspace directory containing agents, skills, and tools. |
| `auth` | `bool \| Callable \| AuthProvider` | `True` | Authentication configuration. `True` reads from `gateway.yaml`. `False` disables auth entirely. Pass an `AuthProvider` instance or a callable for custom auth. |
| `reload` | `bool` | `False` | Enable automatic workspace reload on file changes (development only). |
| `**fastapi_kwargs` | `Any` | — | Forwarded directly to `FastAPI.__init__`. Accepts `title`, `description`, `version`, `docs_url`, `lifespan`, etc. |

Any `lifespan` passed in `fastapi_kwargs` is composed with the Gateway's own lifespan, not replaced.

**OpenAPI tags:** The Gateway automatically registers OpenAPI tag groups (Health, Agents, Chat, Sessions, Conversations, Executions, Schedules, Tools, Skills, User Config, Admin). If you pass `openapi_tags` in `fastapi_kwargs`, your tags are appended after the defaults.

**Example:**

```python
gw = Gateway(
    workspace="./workspace",
    auth=False,
    title="My Agent API",
    version="1.0.0",
)
```

---

## Properties (read-only)

All properties return `None` (or an empty dict) if the gateway has not yet started.

| Property | Type | Description |
|----------|------|-------------|
| `workspace` | `WorkspaceState \| None` | Current workspace state (agents, skills, tools, schedules). |
| `tool_registry` | `ToolRegistry \| None` | Registry of all loaded tools (file-defined and code-registered). |
| `engine` | `ExecutionEngine \| None` | The execution engine driving LLM + tool calls. |
| `agents` | `dict[str, Agent]` | Discovered agents, keyed by agent ID. Empty dict if not loaded. |
| `skills` | `dict[str, Skill]` | Discovered skills, keyed by skill ID. Empty dict if not loaded. |
| `tools` | `dict[str, Any]` | All registered tools, keyed by tool name. Empty dict if not loaded. |
| `memory_manager` | `MemoryManager \| None` | The memory manager instance, if memory is enabled. |
| `scheduler` | `SchedulerEngine \| None` | The scheduler engine, if cron schedules are defined and enabled. |

---

## Lifecycle Methods

### `run`

```python
def run(host: str = "0.0.0.0", port: int = 8000, **kwargs) -> None
```

Start the gateway using uvicorn. Blocks until the server is stopped.

`**kwargs` are forwarded to `uvicorn.run` (e.g. `workers`, `ssl_keyfile`, `log_level`).

```python
gw.run(host="0.0.0.0", port=8000)
```

### `managed` / `async with`

```python
@asynccontextmanager
async def managed() -> AsyncIterator[Gateway]
```

Context manager for non-ASGI usage — CLI scripts, tests, background jobs. Runs full startup and shutdown without an HTTP server.

```python
async with Gateway(workspace="./workspace") as gw:
    result = await gw.invoke("my-agent", "Hello!")
    print(result.raw_text)
```

`async with gw:` is equivalent — `Gateway` implements `__aenter__` / `__aexit__`.

### `reload`

```python
async def reload() -> None
```

Atomically reload the workspace from disk. Rebuilds the tool registry and execution engine from the current workspace files without restarting the server. In-flight executions continue against the old snapshot until they complete.

```python
await gw.reload()
```

### `health`

```python
def health() -> dict[str, Any]
```

Return a status dictionary. Programmatic equivalent of `GET /v1/health`.

```python
{
    "status": "ok",          # "ok" or "degraded"
    "agent_count": 3,
    "skill_count": 5,
    "tool_count": 8,
}
```

---

## Invocation

### `invoke`

```python
async def invoke(
    agent_id: str,
    message: str,
    input: dict[str, Any] | None = None,
    options: ExecutionOptions | None = None,
) -> ExecutionResult
```

Invoke an agent programmatically, bypassing HTTP. Validates input against the agent's schema if one is defined.

| Parameter | Type | Description |
|-----------|------|-------------|
| `agent_id` | `str` | The agent to invoke (directory name under `workspace/agents/`). |
| `message` | `str` | The user message / prompt. |
| `input` | `dict \| None` | Structured input matching the agent's input schema. |
| `options` | `ExecutionOptions \| None` | Overrides for model, temperature, max tokens, guardrails. |

Returns an `ExecutionResult` with `.raw_text`, `.usage`, `.stop_reason`, and `.duration_ms`.

Raises `ValueError` if the agent is not found or the engine is unavailable. Raises `InputValidationError` if the input fails schema validation.

```python
result = await gw.invoke("summariser", "Summarise the Q3 report.")
print(result.raw_text)
```

### `chat`

```python
async def chat(
    agent_id: str,
    message: str,
    session_id: str | None = None,
    input: dict[str, Any] | None = None,
    options: ExecutionOptions | None = None,
    auth: Any | None = None,
) -> tuple[str, ExecutionResult]
```

Send a multi-turn chat message programmatically. Maintains conversation history in an in-memory session store. Persists messages to the database if persistence is enabled.

| Parameter | Type | Description |
|-----------|------|-------------|
| `agent_id` | `str` | The agent to chat with. |
| `message` | `str` | The user's message. |
| `session_id` | `str \| None` | Resume an existing session. Creates a new session if `None`. |
| `input` | `dict \| None` | Metadata merged into the session (not re-validated each turn). |
| `options` | `ExecutionOptions \| None` | Overrides for model, temperature, max tokens, guardrails. |
| `auth` | `Any \| None` | `AuthResult` from the current request, used for user-scoped memory. |

Returns `(session_id, ExecutionResult)`. Use `session_id` to continue the conversation.

```python
session_id, result = await gw.chat("assistant", "Hello!")
session_id, result = await gw.chat("assistant", "Follow up?", session_id=session_id)
```

---

## Session Management

### `get_session`

```python
def get_session(session_id: str) -> ChatSession | None
```

Retrieve a session by ID. Returns `None` if not found or expired.

### `delete_session`

```python
def delete_session(session_id: str) -> bool
```

Delete a session. Returns `True` if the session existed and was deleted.

### `list_sessions`

```python
def list_sessions(agent_id: str | None = None, limit: int = 50) -> list[ChatSession]
```

List active in-memory sessions. Optionally filter by agent. Results are newest-first, capped at `limit`.

---

## Execution Management

### `cancel_execution`

```python
async def cancel_execution(execution_id: str) -> bool
```

Request cancellation of a running execution. Returns `True` if the execution was found and a cancellation signal was sent.

Checks in-memory handles first (same-process sync or async executions), then falls back to the queue backend for cross-process or queued executions. Cancellation is cooperative — the execution may not stop immediately.

---

## Schedule Management

All schedule methods return empty values / `False` if no scheduler is active.

### `list_schedules`

```python
async def list_schedules() -> list[dict[str, Any]]
```

Return all registered cron schedules with their status, next fire time, and last execution result.

### `get_schedule`

```python
async def get_schedule(schedule_id: str) -> dict[str, Any] | None
```

Return details for a single schedule. Returns `None` if not found.

### `pause_schedule`

```python
async def pause_schedule(schedule_id: str) -> bool
```

Pause a schedule so it does not fire. Returns `True` if found and paused.

### `resume_schedule`

```python
async def resume_schedule(schedule_id: str) -> bool
```

Resume a paused schedule. Returns `True` if found and resumed.

### `trigger_schedule`

```python
async def trigger_schedule(schedule_id: str) -> str | None
```

Manually trigger a schedule outside its normal cron cadence. Returns the `execution_id` of the triggered run, or `None` if the schedule was not found.

---

## Fluent Configuration

Fluent methods configure components before startup and return `self` for chaining. All raise `RuntimeError` if called after the gateway has started.

### Persistence

#### `use_sqlite`

```python
def use_sqlite(path: str = "agent_gateway.db", table_prefix: str = "") -> Gateway
```

Configure SQLite persistence. The path `":memory:"` creates a non-durable in-process database useful for tests. Requires `pip install agents-gateway[sqlite]`.

#### `use_postgres`

```python
def use_postgres(
    url: str,
    schema: str | None = None,
    table_prefix: str = "",
    pool_size: int = 10,
    max_overflow: int = 20,
) -> Gateway
```

Configure PostgreSQL persistence. `url` must be an asyncpg DSN (`postgresql+asyncpg://...`). Requires `pip install agents-gateway[postgres]`.

#### `use_persistence`

```python
def use_persistence(backend: PersistenceBackend | None) -> Gateway
```

Provide a custom `PersistenceBackend` implementation. Pass `None` to disable persistence entirely.

---

### Queues

#### `use_memory_queue`

```python
def use_memory_queue() -> Gateway
```

Use an in-process `asyncio.Queue` for async execution. Jobs are lost on restart. Development and testing only. Does not support `--worker-only` mode.

#### `use_redis_queue`

```python
def use_redis_queue(
    url: str = "redis://localhost:6379/0",
    stream_key: str = "ag:executions",
    consumer_group: str = "ag-workers",
) -> Gateway
```

Configure Redis Streams as the queue backend. Requires `pip install agents-gateway[redis]`.

#### `use_rabbitmq_queue`

```python
def use_rabbitmq_queue(
    url: str = "amqp://guest:guest@localhost:5672/",
    queue_name: str = "ag.executions",
) -> Gateway
```

Configure RabbitMQ as the queue backend. Requires `pip install agents-gateway[rabbitmq]`.

#### `use_queue`

```python
def use_queue(backend: ExecutionQueue | None) -> Gateway
```

Provide a custom `ExecutionQueue` implementation. Pass `None` to use the no-op queue.

---

### Auth

#### `use_api_keys`

```python
def use_api_keys(keys: list[dict[str, Any]]) -> Gateway
```

Configure API key authentication. Each dict must have `"key"` and may include `"name"` and `"scopes"` (list of strings, `["*"]` grants all). Keys are hashed immediately and the plaintext is not retained.

```python
gw.use_api_keys([
    {"name": "service-a", "key": "sk-abc123", "scopes": ["*"]},
    {"name": "read-only",  "key": "sk-xyz789", "scopes": ["read"]},
])
```

#### `use_oauth2`

```python
def use_oauth2(
    issuer: str,
    audience: str,
    jwks_uri: str | None = None,
    algorithms: list[str] | None = None,
    scope_claim: str = "scope",
) -> Gateway
```

Configure OAuth2/OIDC JWT validation. `jwks_uri` defaults to `{issuer}/.well-known/jwks.json`. `algorithms` defaults to `["RS256", "ES256"]`. Set `scope_claim="scp"` for Azure AD. Requires `pip install agents-gateway[oauth2]`.

#### `use_auth`

```python
def use_auth(provider: AuthProvider | None) -> Gateway
```

Provide a custom `AuthProvider`. Pass `None` to disable authentication.

---

### Notifications

#### `use_slack_notifications`

```python
def use_slack_notifications(
    bot_token: str,
    default_channel: str = "#agent-alerts",
    templates_dir: Path | str | None = None,
) -> Gateway
```

Configure Slack notifications. `templates_dir` can point to a directory of Jinja2 Block Kit templates (`.json.j2`). Requires `pip install agents-gateway[slack]`.

#### `use_webhook_notifications`

```python
def use_webhook_notifications(
    url: str,
    name: str = "default",
    secret: str = "",
    events: list[str] | None = None,
    payload_template: str | None = None,
) -> Gateway
```

Add a webhook notification endpoint. Can be called multiple times to register multiple endpoints. Agents reference endpoints by `name` in their `AGENT.md` frontmatter. `events` filters which event types trigger this endpoint; empty means all events. `payload_template` is a Jinja2 template string for custom payloads.

#### `use_notifications`

```python
def use_notifications(backend: NotificationBackend | None) -> Gateway
```

Register a custom `NotificationBackend`. Pass `None` to clear all registered backends.

---

### Retrieval

#### `use_retriever`

```python
def use_retriever(name: str, retriever: ContextRetriever) -> Gateway
```

Register a named context retriever. Agents reference retrievers by `name` in their `AGENT.md` frontmatter via the `retrievers:` key. Retrievers are called during prompt assembly to inject dynamic context (e.g. vector search results). Raises `ValueError` if a retriever with the same name is already registered.

---

### Memory

#### `use_memory`

```python
def use_memory(backend: MemoryBackend) -> Gateway
```

Configure a custom memory backend. Only activated for agents with `memory.enabled: true` in their `AGENT.md` frontmatter.

#### `use_file_memory`

```python
def use_file_memory() -> Gateway
```

Use the built-in file-based memory backend. Stores memories as structured markdown (`MEMORY.md`) in each agent's workspace directory. Zero infrastructure required. Line cap is controlled by `memory.max_memory_md_lines` in `gateway.yaml`.

---

### CORS

#### `use_cors`

```python
def use_cors(
    *,
    allow_origins: list[str] | None = None,
    allow_methods: list[str] | None = None,
    allow_headers: list[str] | None = None,
    allow_credentials: bool = False,
    max_age: int = 3600,
) -> Gateway
```

Enable CORS middleware. Defaults: origins `["*"]`, methods `["GET", "POST", "DELETE", "OPTIONS"]`, headers `["Authorization", "Content-Type"]`. `allow_credentials=True` requires explicit origins (wildcard is rejected).

```python
gw.use_cors(allow_origins=["https://app.example.com"], allow_credentials=True)
```

---

### Security Headers

#### `use_security_headers`

```python
def use_security_headers(
    *,
    x_content_type_options: str = "nosniff",
    x_frame_options: str = "DENY",
    strict_transport_security: str = "max-age=31536000; includeSubDomains",
    content_security_policy: str = "default-src 'self'",
    referrer_policy: str = "strict-origin-when-cross-origin",
    dashboard_content_security_policy: str | None = None,
) -> Gateway
```

Customize security headers. Headers are enabled by default -- this method overrides individual values. To disable entirely, set `security.enabled: false` in `gateway.yaml`.

```python
gw.use_security_headers(x_frame_options="SAMEORIGIN")
```

---

### Dashboard

#### `use_dashboard`

```python
def use_dashboard(
    *,
    title: str | None = None,
    logo_url: str | None = None,
    auth_username: str | None = None,
    auth_password: str | None = None,
    theme: str | None = None,            # "light" | "dark" | "auto"
    accent_color: str | None = None,     # legacy; prefer primary_color
    primary_color: str | None = None,
    secondary_color: str | None = None,
    surface_color: str | None = None,
    sidebar_color: str | None = None,
    danger_color: str | None = None,
    oauth2_issuer: str | None = None,
    oauth2_client_id: str | None = None,
    oauth2_client_secret: str | None = None,
    oauth2_scopes: list[str] | None = None,
    login_button_text: str | None = None,
    admin_username: str | None = None,
    admin_password: str | None = None,
) -> Gateway
```

Enable the built-in web dashboard at `/dashboard`. The dashboard has its own session-based authentication independent of the API auth.

Password auth and OAuth2 are mutually exclusive. Setting both raises `ConfigError` at startup. A missing password logs a warning but does not prevent startup.

Optionally configure a separate admin account with `admin_username`/`admin_password`. Admin users can toggle schedules and retry executions. OAuth2 users are always non-admin.

```python
gw.use_dashboard(auth_password="secret", title="My Agents")

# OAuth2/SSO:
gw.use_dashboard(
    oauth2_issuer="https://accounts.google.com",
    oauth2_client_id="...",
    oauth2_client_secret="...",
)
```

---

## Decorators

### `@gw.tool`

Register a Python function as a tool available to agents.

```python
# Bare decorator — name inferred from function name
@gw.tool
def search_docs(query: str) -> str:
    """Search the documentation."""
    ...

# With options
@gw.tool(
    name="search-docs",
    description="Search the documentation knowledge base.",
    allowed_agents=["support-bot"],
    require_approval=False,
)
def search_docs(query: str) -> str:
    ...
```

The decorator supports four parameter inference modes:

1. Explicit `parameters` dict — used as-is (raw JSON Schema `properties`).
2. Single Pydantic `BaseModel` parameter — schema from `model_json_schema()`.
3. `Annotated[type, "description"]` — type and description extracted from annotation.
4. Bare type hints — type inferred, parameter name used as description.

The function name is converted to kebab-case by default (`search_docs` → `search-docs`).

### `@gw.on(event)`

Register an async lifecycle hook callback.

```python
@gw.on("agent.invoke.before")
async def log_invocation(agent_id: str, message: str, execution_id: str, **kw):
    print(f"[{execution_id}] Invoking {agent_id}: {message[:80]}")
```

Hook functions must be `async`. Failures are logged as warnings and never propagate. See the [Hooks reference](hooks.md) for all available events and their payloads.

### `gw.set_input_schema`

```python
def set_input_schema(agent_id: str, schema: dict[str, Any] | type) -> None
```

Set the input schema for an agent programmatically. Accepts a JSON Schema dict or a Pydantic `BaseModel` class. Call before startup. Code-registered schemas override any `input_schema:` defined in `AGENT.md` frontmatter.

```python
from pydantic import BaseModel

class AnalysisInput(BaseModel):
    report_id: str
    quarter: int

gw.set_input_schema("financial-analyst", AnalysisInput)
```
