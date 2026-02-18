---
title: "Phase 2.3b: Queue-Based Execution Backend"
type: feat
status: pending
date: 2026-02-18
depends_on: [11]
blocks: []
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 2.3b: Queue-Based Execution Backend

## Goal

Replace the in-process `asyncio.create_task` execution model with a pluggable queue backend so that async agent invocations survive server restarts, distribute across workers, and enforce fair concurrency limits. The default `memory` backend (current behaviour) stays for development; a `redis` backend is added for production.

## Prerequisites

- Phase 11 (Streaming & Async Execution — memory backend working)

---

## Design

### Backend Protocol

```python
class ExecutionQueue(Protocol):
    async def enqueue(self, job: ExecutionJob) -> None: ...
    async def dequeue(self, timeout: float = 0) -> ExecutionJob | None: ...
    async def ack(self, job_id: str) -> None: ...
    async def nack(self, job_id: str) -> None: ...
    async def cancel(self, job_id: str) -> bool: ...
    async def length(self) -> int: ...
```

### ExecutionJob

```python
@dataclass(frozen=True)
class ExecutionJob:
    execution_id: str
    agent_id: str
    message: str
    context: dict[str, Any] | None
    options: ExecutionOptions
    enqueued_at: datetime
```

### Memory Backend (default)

- Wraps `asyncio.Queue` — same in-process behaviour as today
- Jobs lost on restart (documented)
- No worker process needed — consumer runs as a background task in the same event loop

### Redis Backend

- Uses Redis Streams (`XADD` / `XREADGROUP` / `XACK`)
- Consumer group per gateway instance
- Pending Entry List (PEL) enables crash recovery: unclaimed jobs are re-delivered after a configurable timeout
- Cancellation: set a Redis key `cancel:{execution_id}` — worker checks before each LLM call
- Job payload serialised as JSON

### Worker Loop

A single `_worker_loop` coroutine runs inside the gateway process (started in `_startup`, drained in `_shutdown`):

```
while not shutting_down:
    job = await queue.dequeue(timeout=1.0)
    if job is None:
        continue
    if job is cancelled:
        await queue.ack(job.job_id)
        continue
    async with execution_semaphore:
        await run_execution(job)
    await queue.ack(job.job_id)
```

For horizontal scaling, run additional gateway instances with `--worker-only` (serves no HTTP, just consumes from queue).

---

## Configuration

Extends existing `QueueConfig` in `config.py`:

```yaml
queue:
  backend: memory          # or "redis"
  redis_url: redis://localhost:6379/0
  stream_key: ag:executions
  consumer_group: ag-workers
  max_retries: 3
  visibility_timeout_s: 300   # re-deliver if not acked within 5 min
  workers: 4                  # concurrent jobs per process
```

`workers` replaces the current `_MAX_CONCURRENT_EXECUTIONS` constant and controls the semaphore size.

---

## Tasks

### 1. Define Queue Protocol & Job Model

- Add `ExecutionQueue` protocol to `engine/queue.py`
- Add `ExecutionJob` frozen dataclass
- Add `enqueued_at`, `dequeued_at` columns to `ExecutionRecord`

### 2. Memory Backend

- Implement `MemoryQueue(ExecutionQueue)` wrapping `asyncio.Queue`
- Wire into gateway as default backend
- Migrate `invoke.py` async path from `asyncio.create_task` → `queue.enqueue`

### 3. Worker Loop

- Add `_worker_loop` to `Gateway`
- Start N worker coroutines in `_startup` (configurable via `queue.workers`)
- Graceful drain in `_shutdown`: stop accepting, finish in-flight, timeout remaining

### 4. Redis Backend

- Implement `RedisQueue(ExecutionQueue)` using `redis.asyncio`
- Redis Streams: `XADD`, `XREADGROUP`, `XACK`, `XDEL`
- Consumer group auto-creation on startup
- PEL recovery: claim stale entries on startup
- Cancellation via `cancel:{id}` key with TTL

### 5. CLI: `--worker-only` Mode

- Add `--worker-only` flag to `serve` command
- Skips HTTP server, only runs worker loop
- Useful for horizontal scaling

### 6. Observability

- Queue depth metric (gauge)
- Job latency metric (histogram: enqueue → dequeue)
- Worker utilisation metric (gauge: active / total)
- Dead-letter logging for jobs exceeding `max_retries`

---

## Tests

**Memory backend:**
- Enqueue/dequeue round-trip
- Cancel before dequeue
- Worker loop processes job end-to-end
- Graceful shutdown drains in-flight jobs

**Redis backend:**
- Enqueue/dequeue with real Redis (integration test, skipped without Redis)
- Consumer group creation
- PEL recovery after simulated crash
- Cancellation via key
- Visibility timeout re-delivery

**API integration:**
- `POST /agents/{id}/invoke` with `async: true` enqueues job
- `GET /executions/{id}` reflects queue → running → completed transitions
- `POST /executions/{id}/cancel` cancels queued job

---

## Acceptance Criteria

- [ ] `queue.backend: memory` works identically to current async behaviour
- [ ] `queue.backend: redis` enqueues to Redis Streams
- [ ] Unclaimed jobs re-delivered after visibility timeout
- [ ] Cancellation works for both queued and in-flight jobs
- [ ] `--worker-only` mode consumes without serving HTTP
- [ ] Queue depth and job latency metrics emitted
- [ ] Graceful shutdown drains in-flight jobs within timeout
- [ ] Existing tests still pass with memory backend (no regression)
