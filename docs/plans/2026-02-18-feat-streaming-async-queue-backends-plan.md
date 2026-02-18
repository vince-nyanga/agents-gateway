---
title: "feat: Streaming, Async Execution & Pluggable Queue Backends"
type: feat
status: completed
date: 2026-02-18
depends_on: [08, 08b]
blocks: [10]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
supersedes: [11-streaming-and-async.md, 11b-queue-based-execution.md]
---

# Streaming, Async Execution & Pluggable Queue Backends

## Overview

Add pluggable queue backends for async agent execution, following the same `agent-gateway[redis]` / `agent-gateway[rabbitmq]` extras pattern used for persistence and auth. Agents declare their execution mode (`sync` or `async`) in frontmatter. Sync agents run inline. Async agents are queued, and results are delivered via polling or notifications (Phase 10).

## Problem Statement

Today, async execution uses bare `asyncio.create_task` — jobs are lost on restart, cannot distribute across workers, and have no durable delivery guarantees. Production deployments need:

- **Durability**: async jobs survive server restarts
- **Horizontal scaling**: separate worker processes consume from a shared queue
- **Agent-level control**: agent authors declare whether their agent is sync or async
- **Pluggable backends**: memory for dev, Redis/RabbitMQ for production

## Architecture Decision: Execution Mode Resolution

This is the most critical design decision. The rule is simple:

```
Agent config is a FLOOR, not a ceiling.
```

| Agent `execution_mode` | Request `async: true` | Request `async: false` / absent | Behaviour |
|---|---|---|---|
| `sync` (default) | Queue (client escalates) | Inline 200 | Client can opt into async |
| `async` | Queue | Queue (agent forces it) | Agent always queues |

**Rationale**: An agent author who sets `execution_mode: async` is saying "this agent does long-running work and MUST be queued." A client cannot override this — it would bypass the architectural constraint the agent author intended. But a client CAN escalate a sync agent to async (useful for fire-and-forget patterns).

**Implementation**: A single function in `invoke.py`:

```python
# src/agent_gateway/api/routes/invoke.py
def _should_queue(agent: AgentDefinition, request_async: bool) -> bool:
    if agent.execution_mode == "async":
        return True  # agent forces queuing
    return request_async  # client's choice
```

## Architecture Decision: Streaming + Async Incompatibility

SSE streaming and queued execution are architecturally incompatible. A queued job runs in a worker (possibly a different process) — there is no live connection to stream tokens through.

**Rule**: If a client requests streaming (`Accept: text/event-stream` or `options.stream: true`) for an agent with `execution_mode: async`, return **400 Bad Request**:

```json
{"error": "streaming_not_supported", "detail": "Streaming is not available for async agents. Use polling or callbacks."}
```

If a client sends both `async: true` AND `stream: true` on a sync agent, `async` wins — return 202 with poll URL (not a stream).

## Proposed Solution

### Package Structure (Extras Pattern)

```toml
# pyproject.toml
[project.optional-dependencies]
redis = ["redis>=5.0"]           # already exists — used for queue + cache
rabbitmq = ["aio-pika>=9.0"]     # NEW — AMQP 0-9-1 client
all = ["agent-gateway[sqlite,postgres,otlp,oauth2,slack,redis,rabbitmq]"]
```

### Fluent API

```python
gw = Gateway(workspace="./workspace")

# Queue backends (mutually exclusive, like persistence)
gw.use_memory_queue()                              # default, dev only
gw.use_redis_queue(url="redis://localhost:6379/0")  # production
gw.use_rabbitmq_queue(url="amqp://guest:guest@localhost:5672/")  # production alt
gw.use_queue(custom_backend)                        # bring your own

# Existing patterns unchanged
gw.use_sqlite(path="gateway.db")
gw.use_api_keys(keys=[...])
```

### gateway.yaml Config

```yaml
queue:
  backend: memory          # memory | redis | rabbitmq
  redis_url: redis://localhost:6379/0
  rabbitmq_url: amqp://guest:guest@localhost:5672/
  stream_key: ag:executions          # Redis stream name
  queue_name: ag.executions          # RabbitMQ queue name
  consumer_group: ag-workers         # Redis consumer group / RabbitMQ consumer tag prefix
  workers: 4                         # concurrent jobs per process
  max_retries: 3                     # before dead-lettering
  visibility_timeout_s: 300          # Redis PEL re-delivery / RabbitMQ requeue timeout
  drain_timeout_s: 30                # graceful shutdown wait
  default_execution_mode: sync       # global default for agents without explicit config
```

---

## Technical Approach

### Agent Config: `execution_mode` Field

Add `execution_mode` to `AgentDefinition` and parse from AGENT.md / CONFIG.md frontmatter:

```python
# src/agent_gateway/workspace/agent.py

@dataclass
class AgentDefinition:
    id: str
    path: Path
    agent_prompt: str
    soul_prompt: str = ""
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    model: AgentModelConfig = field(default_factory=AgentModelConfig)
    schedules: list[ScheduleConfig] = field(default_factory=list)
    execution_mode: str = "sync"  # NEW: "sync" | "async"
```

Agent authors set it in frontmatter:

```yaml
# workspace/agents/report-generator/AGENT.md
---
skills:
  - data-analysis
tools:
  - fetch-dataset
  - generate-pdf
execution_mode: async
---
You are a report generator. You fetch large datasets and produce PDF reports.
This is a long-running task that typically takes 2-5 minutes.
```

**Parse rule**: `CONFIG.md` wins over `AGENT.md` (scalar precedence, same as `model`). Falls back to `queue.default_execution_mode` from gateway.yaml, then `"sync"`.

### Queue Protocol

```python
# src/agent_gateway/queue/protocol.py

@runtime_checkable
class ExecutionQueue(Protocol):
    """Pluggable queue backend for async agent execution."""

    async def initialize(self) -> None: ...
    async def dispose(self) -> None: ...
    async def enqueue(self, job: ExecutionJob) -> None: ...
    async def dequeue(self, timeout: float = 0) -> ExecutionJob | None: ...
    async def ack(self, job_id: str) -> None: ...
    async def nack(self, job_id: str) -> None: ...
    async def request_cancel(self, job_id: str) -> bool: ...
    async def is_cancelled(self, job_id: str) -> bool: ...
    async def length(self) -> int: ...
```

Key design choices:
- **`request_cancel` + `is_cancelled`** replace the ambiguous `cancel`. The cancel endpoint calls `request_cancel`; the worker calls `is_cancelled` before each LLM iteration.
- **`nack` semantics**: re-queue the job for retry. Memory backend re-enqueues. Redis uses PEL (no explicit nack needed, just don't ack). RabbitMQ uses `basic_nack(requeue=True)`.

### ExecutionJob Model

```python
# src/agent_gateway/queue/models.py

@dataclass(frozen=True)
class ExecutionJob:
    execution_id: str
    agent_id: str
    message: str
    context: dict[str, Any] | None
    timeout_ms: int | None
    output_schema: dict[str, Any] | None
    callback_url: str | None          # for completion callback
    enqueued_at: str                   # ISO 8601 string (not datetime — JSON-safe)
    retry_count: int = 0              # tracked for max_retries enforcement

    def to_json(self) -> str: ...     # json.dumps with no custom encoder needed

    @classmethod
    def from_json(cls, data: str) -> ExecutionJob: ...
```

**All fields are JSON-primitive types** — no `datetime`, no nested Protocol objects. The `enqueued_at` is an ISO 8601 string. `ExecutionOptions` is flattened into individual fields to avoid nested serialisation issues.

### Backend Implementations

#### Memory Backend (Default)

```python
# src/agent_gateway/queue/backends/memory.py

class MemoryQueue:
    """In-process asyncio.Queue wrapper. Dev/test only."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ExecutionJob] = asyncio.Queue()
        self._cancelled: set[str] = set()  # execution_ids

    async def request_cancel(self, job_id: str) -> bool:
        self._cancelled.add(job_id)
        return True

    async def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled
```

**Limitations** (documented in docstring + README):
- Jobs lost on restart
- Single-process only — `--worker-only` mode requires Redis or RabbitMQ
- No crash recovery

#### Redis Backend

```python
# src/agent_gateway/queue/backends/redis.py

class RedisQueue:
    """Redis Streams backend. Requires: pip install agent-gateway[redis]"""

    # Uses XADD / XREADGROUP / XACK
    # Consumer group auto-created on initialize()
    # Cancel via SET cancel:{execution_id} with TTL = visibility_timeout_s
    # PEL recovery: XAUTOCLAIM stale entries on startup
    # Retry count: XPENDING delivery count (built into Redis Streams)
    # Dead letter: XDEL from stream + update execution record to DEAD_LETTERED
```

#### RabbitMQ Backend

```python
# src/agent_gateway/queue/backends/rabbitmq.py

class RabbitMQQueue:
    """RabbitMQ backend via aio-pika. Requires: pip install agent-gateway[rabbitmq]"""

    # Uses a durable queue with manual ack
    # Cancel via message header check (publish cancel message to a fanout exchange)
    # DLX (Dead Letter Exchange) for max_retries exceeded
    # Prefetch count = workers config
    # Retry count: x-delivery-count header (RabbitMQ quorum queues)
    #   OR custom header incremented on nack+requeue
```

**RabbitMQ-specific design**:
- **Queue**: `ag.executions` (durable, quorum queue for delivery count tracking)
- **DLX**: `ag.executions.dlx` → `ag.executions.dead-letter` queue
- **Cancel exchange**: `ag.cancel` (fanout) — workers subscribe; cancel endpoint publishes `{execution_id}`
- **Prefetch**: Set to `workers` config value

### Worker Loop

```python
# src/agent_gateway/queue/worker.py

class WorkerPool:
    """Manages N worker coroutines consuming from the queue."""

    def __init__(self, queue: ExecutionQueue, gateway: Gateway, config: QueueConfig):
        self._queue = queue
        self._gateway = gateway
        self._config = config
        self._tasks: list[asyncio.Task] = []
        self._shutting_down = False

    async def start(self) -> None:
        for i in range(self._config.workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"worker-{i}")
            self._tasks.append(task)

    async def drain(self) -> None:
        self._shutting_down = True
        # Wait for in-flight jobs up to drain_timeout_s
        # Then cancel remaining tasks

    async def _worker_loop(self, worker_id: int) -> None:
        while not self._shutting_down:
            job = await self._queue.dequeue(timeout=1.0)
            if job is None:
                continue

            # Check cancel BEFORE execution
            if await self._queue.is_cancelled(job.execution_id):
                await self._queue.ack(job.execution_id)
                await self._gateway._execution_repo.update_status(
                    job.execution_id, ExecutionStatus.CANCELLED
                )
                continue

            # Check max_retries
            if job.retry_count > self._config.max_retries:
                await self._queue.ack(job.execution_id)
                await self._gateway._execution_repo.update_status(
                    job.execution_id, ExecutionStatus.FAILED, error="max retries exceeded"
                )
                continue

            try:
                await self._run_execution(job)
                await self._queue.ack(job.execution_id)
            except Exception:
                await self._queue.nack(job.execution_id)  # re-queue for retry
```

### Cancel Endpoint Update

The cancel endpoint must be queue-aware:

```python
# src/agent_gateway/api/routes/executions.py (updated)

async def cancel_execution(execution_id: str, request: Request):
    gw: Gateway = request.app

    # 1. Try in-memory handle (sync execution or same-process async)
    handle = gw._execution_handles.get(execution_id)
    if handle is not None:
        handle.cancel()
        return {"status": "cancelled"}

    # 2. Try queue backend (queued or running on another worker)
    if gw._queue is not None:
        cancelled = await gw._queue.request_cancel(execution_id)
        if cancelled:
            return {"status": "cancel_requested"}

    # 3. Check persistence for terminal state
    record = await gw._execution_repo.get(execution_id)
    if record and record.status in terminal_states:
        return JSONResponse(status_code=409, content={"error": "already_completed"})

    return JSONResponse(status_code=404, content={"error": "not_found"})
```

### Invoke Endpoint Update

```python
# src/agent_gateway/api/routes/invoke.py (updated)

@router.post("/agents/{agent_id}/invoke")
async def invoke_agent(body: InvokeRequest, request: Request, agent_id: str):
    gw: Gateway = request.app
    # ... existing validation ...

    should_queue = _should_queue(agent, body.options.async_)

    # Guard: streaming + async incompatible
    if should_queue and body.options.stream:
        return error_response(400, "streaming_not_supported",
            "Streaming is not available for async agents")

    if should_queue:
        job = ExecutionJob(
            execution_id=execution_id,
            agent_id=agent_id,
            message=body.message,
            context=body.context,
            timeout_ms=body.options.timeout_ms,
            output_schema=body.options.output_schema,
            callback_url=body.options.callback_url,
            enqueued_at=datetime.now(UTC).isoformat(),
        )
        await gw._queue.enqueue(job)
        return JSONResponse(status_code=202, content={
            "execution_id": execution_id,
            "agent_id": agent_id,
            "status": "queued",
            "poll_url": f"/v1/executions/{execution_id}",
        })

    # Sync execution (unchanged)
    ...
```

### Gateway Fluent API Additions

```python
# src/agent_gateway/gateway.py (additions)

class Gateway(FastAPI):

    def use_memory_queue(self) -> Gateway:
        """Use in-process queue (default, dev only). Jobs lost on restart."""
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        from agent_gateway.queue.backends.memory import MemoryQueue
        self._queue_backend = MemoryQueue()
        return self

    def use_redis_queue(
        self,
        url: str = "redis://localhost:6379/0",
        stream_key: str = "ag:executions",
        consumer_group: str = "ag-workers",
    ) -> Gateway:
        """Configure Redis Streams queue backend.

        Requires: pip install agent-gateway[redis]
        """
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        from agent_gateway.queue.backends.redis import RedisQueue
        self._queue_backend = RedisQueue(
            url=url, stream_key=stream_key, consumer_group=consumer_group
        )
        return self

    def use_rabbitmq_queue(
        self,
        url: str = "amqp://guest:guest@localhost:5672/",
        queue_name: str = "ag.executions",
    ) -> Gateway:
        """Configure RabbitMQ queue backend.

        Requires: pip install agent-gateway[rabbitmq]
        """
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        from agent_gateway.queue.backends.rabbitmq import RabbitMQQueue
        self._queue_backend = RabbitMQQueue(url=url, queue_name=queue_name)
        return self

    def use_queue(self, backend: ExecutionQueue | None) -> Gateway:
        """Configure a custom queue backend, or None to use memory (default)."""
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        self._queue_backend = backend
        return self
```

### `--worker-only` Mode

A worker-only process is a **full Gateway instance with HTTP disabled**:

```python
# src/agent_gateway/cli/main.py

@app.command()
def serve(
    workspace: str = "./workspace",
    worker_only: bool = typer.Option(False, help="Run workers only, no HTTP server"),
):
    if worker_only:
        gw = Gateway(workspace=workspace)
        # Full startup (workspace, tools, engine, persistence, queue)
        # But no uvicorn — just run worker pool until SIGTERM
        asyncio.run(_run_worker_only(gw))
    else:
        # Normal: HTTP + workers
        ...
```

**Critical constraint**: `--worker-only` requires a durable queue backend (Redis or RabbitMQ). Memory queue is single-process and cannot be shared. Raise `RuntimeError` if `--worker-only` is used with memory backend.

### Programmatic API

```python
# Same pattern as gw.invoke() — bypass HTTP

gw = Gateway(workspace="./workspace")
gw.use_redis_queue(url="redis://localhost:6379")

async with gw:
    # Sync invocation (unchanged)
    result = await gw.invoke("assistant", "Hello")

    # Queue an async job programmatically
    execution_id = await gw.enqueue("report-generator", "Generate Q4 report")

    # Poll for result
    record = await gw.get_execution(execution_id)
```

---

## Implementation Phases

### Phase 1: Agent Config + Execution Mode Resolution
- Add `execution_mode` field to `AgentDefinition`
- Parse from AGENT.md / CONFIG.md frontmatter
- Add `default_execution_mode` to `QueueConfig`
- Add `_should_queue()` function to invoke route
- Add streaming + async guard (400 error)
- Add `callback_url` to `ExecutionOptions`

**Files**: `workspace/agent.py`, `config.py`, `engine/models.py`, `api/routes/invoke.py`

### Phase 2: Queue Protocol + Memory Backend
- Define `ExecutionQueue` protocol in `queue/protocol.py`
- Define `ExecutionJob` in `queue/models.py`
- Implement `MemoryQueue` in `queue/backends/memory.py`
- Implement `NullQueue` (no-op, used when queue is disabled)
- Wire `_queue_backend` into Gateway lifecycle (`_startup`, `_shutdown`)
- Add fluent methods: `use_memory_queue()`, `use_queue()`
- Migrate `invoke.py` async path from `asyncio.create_task` → `queue.enqueue`

**Files**: `queue/__init__.py`, `queue/protocol.py`, `queue/models.py`, `queue/backends/memory.py`, `queue/null.py`, `gateway.py`, `api/routes/invoke.py`

### Phase 3: Worker Pool
- Implement `WorkerPool` in `queue/worker.py`
- Start workers in `Gateway._startup()`, drain in `_shutdown()`
- Add `drain_timeout_s` to `QueueConfig`
- Update cancel endpoint to be queue-aware
- Defer semaphore creation to `_startup` (use `workers` config)

**Files**: `queue/worker.py`, `gateway.py`, `api/routes/executions.py`, `config.py`

### Phase 4: Redis Backend
- Implement `RedisQueue` using Redis Streams
- Consumer group auto-creation, PEL recovery via `XAUTOCLAIM`
- Cancel via `SET cancel:{id}` with TTL
- Retry count via `XPENDING` delivery count
- Dead-letter: `XDEL` + update execution record status
- Add fluent method: `use_redis_queue()`

**Files**: `queue/backends/redis.py`, `gateway.py`

### Phase 5: RabbitMQ Backend
- Implement `RabbitMQQueue` using `aio-pika`
- Durable quorum queue with manual ack
- DLX for dead-lettering
- Cancel via fanout exchange
- Add `rabbitmq` optional dependency
- Add fluent method: `use_rabbitmq_queue()`

**Files**: `queue/backends/rabbitmq.py`, `gateway.py`, `pyproject.toml`

### Phase 6: CLI `--worker-only` + Observability
- Add `--worker-only` flag to `serve` command
- Guard: reject memory backend with `--worker-only`
- Full Gateway bootstrap minus HTTP server
- Queue depth gauge, job latency histogram, worker utilisation gauge
- Dead-letter counter

**Files**: `cli/main.py`, `telemetry/`

---

## File Structure

```
src/agent_gateway/
    queue/
        __init__.py              # Exports ExecutionQueue, ExecutionJob
        protocol.py              # ExecutionQueue Protocol
        models.py                # ExecutionJob frozen dataclass
        worker.py                # WorkerPool
        null.py                  # NullQueue (no-op default)
        backends/
            __init__.py
            memory.py            # MemoryQueue (asyncio.Queue wrapper)
            redis.py             # RedisQueue (Redis Streams)
            rabbitmq.py          # RabbitMQQueue (aio-pika)
```

## ERD: Queue & Execution State

```mermaid
erDiagram
    ExecutionRecord {
        string id PK
        string agent_id
        string status
        string message
        json context
        json result
        json usage
        string error
        datetime started_at
        datetime completed_at
        datetime enqueued_at
        datetime dequeued_at
    }

    ExecutionJob {
        string execution_id PK
        string agent_id
        string message
        json context
        int timeout_ms
        json output_schema
        string callback_url
        string enqueued_at
        int retry_count
    }

    AgentDefinition {
        string id PK
        string execution_mode
        string model_name
        list skills
        list tools
    }

    AgentDefinition ||--o{ ExecutionRecord : "produces"
    ExecutionRecord ||--|| ExecutionJob : "serialised as"
```

## Execution State Machine

```mermaid
stateDiagram-v2
    [*] --> queued : enqueue
    queued --> running : worker dequeues
    queued --> cancelled : cancel requested
    running --> completed : success
    running --> failed : error
    running --> cancelled : cancel requested
    running --> timeout : timeout exceeded
    failed --> queued : retry (nack)
    failed --> dead_lettered : max_retries exceeded
```

## Acceptance Criteria

### Functional
- [x] Agents can declare `execution_mode: async` in AGENT.md frontmatter
- [x] `execution_mode: async` agents always return 202, regardless of request options
- [x] `execution_mode: sync` agents honour request-level `async: true` escalation
- [x] Streaming + async returns 400 Bad Request
- [x] `gw.use_memory_queue()` works identically to current async behaviour
- [x] `gw.use_redis_queue()` enqueues to Redis Streams with consumer groups
- [x] `gw.use_rabbitmq_queue()` enqueues to RabbitMQ durable queue
- [x] Worker pool starts N workers, drains gracefully on shutdown
- [x] Cancel works for both queued and in-flight jobs across all backends
- [x] Jobs exceeding `max_retries` are dead-lettered
- [x] `--worker-only` mode runs full Gateway without HTTP server
- [x] `--worker-only` rejects memory backend with clear error
- [ ] Callback URL called with HMAC on completion (when configured) — deferred to Phase 10 (notifications)

### Non-Functional
- [x] Queue depth, job latency, and worker utilisation metrics emitted
- [x] Memory backend limitations documented in docstrings and README
- [x] All backends pass the same integration test suite (parameterised)
- [x] Redis/RabbitMQ tests skipped without the service running (graceful skip)

## References

### Internal
- Existing streaming: `src/agent_gateway/engine/streaming.py`
- Current async: `src/agent_gateway/api/routes/invoke.py:120`
- Persistence pattern: `src/agent_gateway/persistence/backend.py`
- Auth pattern: `src/agent_gateway/auth/protocols.py`
- Agent config: `src/agent_gateway/workspace/agent.py`
- Gateway fluent API: `src/agent_gateway/gateway.py:352-416`

### Previous Plans (Superseded)
- `docs/plans/11-streaming-and-async.md` — SSE + memory async
- `docs/plans/11b-queue-based-execution.md` — queue protocol + Redis

### External
- [Redis Streams](https://redis.io/docs/data-types/streams/) — XADD, XREADGROUP, XACK, XAUTOCLAIM
- [aio-pika](https://aio-pika.readthedocs.io/) — asyncio RabbitMQ client
- [RabbitMQ Quorum Queues](https://www.rabbitmq.com/docs/quorum-queues) — delivery count tracking
