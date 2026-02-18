---
title: "Phase 1.6: OpenTelemetry & Persistence"
type: feat
status: completed
date: 2026-02-18
depends_on: [01]
blocks: [08]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.6: OpenTelemetry & Persistence

## Goal

Set up OpenTelemetry traces + metrics and the SQLAlchemy async persistence layer. After this phase, every execution produces console traces and execution history is stored in SQLite.

## Prerequisites

- Phase 01 (config)

---

## Tasks

### 1. Telemetry Bootstrap

**File:** `src/agent_gateway/telemetry/__init__.py`

```python
def setup_telemetry(config: TelemetryConfig) -> None:
    """Initialize OpenTelemetry. Never raises — logs warnings on failure."""
```

- Create `Resource` with `service.name` from config
- Set up `TracerProvider` with `BatchSpanProcessor`
- Set up `MeterProvider` with `PeriodicExportingMetricReader`
- Exporter selection: `console` → `ConsoleSpanExporter`, `otlp` → `OTLPSpanExporter` (requires otlp extra), `none` → noop
- Auto-detect: if `OTEL_EXPORTER_OTLP_ENDPOINT` env var set, use OTLP regardless of config
- Wrap everything in try/except — telemetry failure never crashes the server

### 2. Tracing Helpers

**File:** `src/agent_gateway/telemetry/tracing.py`

Span helper functions used throughout the codebase:

```python
def get_tracer(name: str = "agent-gateway") -> Tracer: ...

@contextmanager
def agent_invoke_span(agent_id: str, execution_id: str): ...

@contextmanager
def llm_call_span(model: str, agent_id: str): ...

@contextmanager
def tool_execute_span(tool_name: str, tool_type: str): ...

@contextmanager
def output_validate_span(): ...
```

Each span sets appropriate GenAI semantic convention attributes.

### 3. Metrics Definitions

**File:** `src/agent_gateway/telemetry/metrics.py`

Define all counters and histograms:

```python
def create_metrics(meter: Meter) -> AgentGatewayMetrics:
    return AgentGatewayMetrics(
        executions_total=meter.create_counter("agw.executions.total"),
        executions_duration=meter.create_histogram("agw.executions.duration_ms"),
        llm_calls_total=meter.create_counter("agw.llm.calls.total"),
        llm_duration=meter.create_histogram("agw.llm.duration_ms"),
        llm_tokens_input=meter.create_counter("agw.llm.tokens.input"),
        llm_tokens_output=meter.create_counter("agw.llm.tokens.output"),
        llm_cost_usd=meter.create_counter("agw.llm.cost_usd"),
        tools_calls_total=meter.create_counter("agw.tools.calls.total"),
        tools_duration=meter.create_histogram("agw.tools.duration_ms"),
        schedules_runs_total=meter.create_counter("agw.schedules.runs.total"),
    )
```

### 4. GenAI Attributes

**File:** `src/agent_gateway/telemetry/attributes.py`

Constants for OpenTelemetry GenAI semantic conventions.

### 5. Persistence Models

**File:** `src/agent_gateway/persistence/models.py`

SQLAlchemy 2.0 declarative models:

- `ExecutionRecord`: id, agent_id, status, message, context (JSON), options (JSON), result (JSON), error, usage (JSON), started_at, completed_at, created_at
- `ExecutionStep`: id, execution_id (FK), step_type (llm_call|tool_call|tool_result), sequence, data (JSON), duration_ms, created_at
- `AuditLogEntry`: id, event_type, actor, resource_type, resource_id, metadata (JSON), ip_address, created_at

Use `mapped_column()` style. JSON columns use `sqlalchemy.JSON`.

### 6. Session Management

**File:** `src/agent_gateway/persistence/session.py`

- `create_db_engine(config: PersistenceConfig) -> AsyncEngine`
- `create_session_factory(engine: AsyncEngine) -> async_sessionmaker`
- `init_db(engine: AsyncEngine)` — create tables via `conn.run_sync(Base.metadata.create_all)`
- Always `expire_on_commit=False`

### 7. Repository

**File:** `src/agent_gateway/persistence/repository.py`

CRUD operations:

```python
class ExecutionRepository:
    async def create(self, execution: ExecutionRecord) -> None: ...
    async def get(self, execution_id: str) -> ExecutionRecord | None: ...
    async def update_status(self, execution_id: str, status: str, **fields) -> None: ...
    async def update_result(self, execution_id: str, result: dict, usage: dict) -> None: ...
    async def list_by_agent(self, agent_id: str, limit: int = 50) -> list[ExecutionRecord]: ...
    async def add_step(self, step: ExecutionStep) -> None: ...

class AuditRepository:
    async def log(self, event_type: str, **kwargs) -> None: ...
```

### 8. NullPersistence

**File:** `src/agent_gateway/persistence/null.py`

No-op implementation for when persistence is disabled or DB is unavailable. Same interface, does nothing.

---

## Tests

**Telemetry:** Setup with console exporter works, setup with `enabled: false` is noop, setup failure doesn't crash.

**Persistence:** Create/read/update executions, add steps, audit log entries, NullPersistence does nothing without errors, init_db creates tables in temp SQLite.

## Acceptance Criteria

- [x] `setup_telemetry()` works with console exporter
- [x] Span helpers create properly attributed spans
- [x] Metrics are defined and can be recorded
- [x] SQLAlchemy models create correct schema
- [x] CRUD operations work with async SQLite
- [x] NullPersistence works as fallback
- [x] All tests pass
