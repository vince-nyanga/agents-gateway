---
title: "feat: Pluggable Persistence Backends"
type: feat
status: completed
date: 2026-02-18
depends_on: [06-telemetry-and-persistence]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Pluggable Persistence Backends

## Overview

Redesign the persistence layer to decouple domain models from SQLAlchemy, introduce backend-agnostic repository protocols over plain dataclasses, and expose an intuitive fluent API for selecting and configuring database backends. Ship SQLite and PostgreSQL as optional pip extras (`agent-gateway[sqlite]`, `agent-gateway[postgres]`), with the architecture open for NoSQL backends.

## Problem Statement

The current persistence layer has three coupling issues:

1. **Domain models are SQLAlchemy ORM classes.** `ExecutionRecord`, `ExecutionStep`, `AuditLogEntry` all inherit from `DeclarativeBase`. Every consumer — protocols, null repos, API routes, invoke logic — imports from `persistence/models.py` and is coupled to SQLAlchemy.

2. **No backend abstraction.** `session.py` creates engines directly, `repository.py` uses SQLAlchemy sessions directly. Adding PostgreSQL-specific pool config or a MongoDB backend requires touching the same files.

3. **Hard dependency on aiosqlite.** It's in core `dependencies` (pyproject.toml line 32), meaning PostgreSQL-only deployments still install SQLite drivers.

## Proposed Solution

A three-layer architecture:

```
┌─────────────────────────────────────────────────────┐
│  Gateway / Routes / Engine  (consumers)             │
│  Import only: domain.py + protocols.py              │
├─────────────────────────────────────────────────────┤
│  persistence/domain.py     — plain @dataclass       │
│  persistence/protocols.py  — typing.Protocol        │
│  persistence/null.py       — NullRepository         │
├─────────────────────────────────────────────────────┤
│  persistence/backends/sqlite/   — SQLAlchemy+aiosqlite │
│  persistence/backends/postgres/ — SQLAlchemy+asyncpg   │
│  persistence/backends/???/      — future NoSQL         │
└─────────────────────────────────────────────────────┘
```

## Dream API

```python
from agent_gateway import Gateway

# SQLite (development)
gw = Gateway(workspace="./workspace")
gw.use_sqlite("dev.db")

# PostgreSQL (production)
gw = Gateway(workspace="./workspace")
gw.use_postgres(
    "postgresql+asyncpg://user:pass@localhost/mydb",
    schema="agent_gateway",
    table_prefix="ag_",
)

# Disabled (testing)
gw = Gateway(workspace="./workspace")
gw.use_persistence(None)

# YAML config still works (backward compat)
# gateway.yaml:
#   persistence:
#     backend: postgres
#     url: postgresql+asyncpg://...
#     schema: agent_gateway
#     table_prefix: ag_
```

## Technical Approach

### Architecture

#### Layer 1: Domain Dataclasses

**File:** `src/agent_gateway/persistence/domain.py`

Plain Python dataclasses with zero ORM imports. These are the types that flow through protocols, routes, and the engine.

```python
# persistence/domain.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class ExecutionRecord:
    id: str
    agent_id: str
    status: str = "queued"
    message: str = ""
    context: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    steps: list[ExecutionStep] = field(default_factory=list)

@dataclass
class ExecutionStep:
    execution_id: str
    step_type: str
    sequence: int
    id: int = 0
    data: dict[str, Any] | None = None
    duration_ms: int = 0
    created_at: datetime | None = None

@dataclass
class AuditLogEntry:
    event_type: str
    id: int = 0
    actor: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at: datetime | None = None

@dataclass
class ScheduleRecord:
    id: str
    agent_id: str
    name: str
    cron_expr: str
    message: str
    context: dict[str, Any] | None = None
    enabled: bool = True
    timezone: str = "UTC"
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
```

#### Layer 2: Protocols (updated imports)

**File:** `src/agent_gateway/persistence/protocols.py`

Same Protocol interfaces, but now referencing `domain.py` instead of `models.py`:

```python
from agent_gateway.persistence.domain import (
    AuditLogEntry, ExecutionRecord, ExecutionStep,
)

@runtime_checkable
class ExecutionRepository(Protocol):
    async def create(self, execution: ExecutionRecord) -> None: ...
    async def get(self, execution_id: str) -> ExecutionRecord | None: ...
    async def update_status(self, execution_id: str, status: str, **fields: Any) -> None: ...
    async def update_result(self, execution_id: str, result: dict, usage: dict) -> None: ...
    async def list_by_agent(self, agent_id: str, limit: int = 50) -> list[ExecutionRecord]: ...
    async def add_step(self, step: ExecutionStep) -> None: ...
```

#### Layer 3: Backend Interface

**File:** `src/agent_gateway/persistence/backend.py`

A Protocol that each backend must satisfy. This is what `Gateway` interacts with to bootstrap persistence:

```python
# persistence/backend.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from agent_gateway.persistence.protocols import ExecutionRepository, AuditRepository

@runtime_checkable
class PersistenceBackend(Protocol):
    """Contract for a pluggable persistence backend."""

    async def initialize(self) -> None:
        """Create tables/collections/indexes. Idempotent."""
        ...

    async def dispose(self) -> None:
        """Close connections and release resources."""
        ...

    @property
    def execution_repo(self) -> ExecutionRepository: ...

    @property
    def audit_repo(self) -> AuditRepository: ...
```

#### Layer 4: SQL Base Backend

**File:** `src/agent_gateway/persistence/backends/sql/base.py`

Shared SQLAlchemy logic for both SQLite and PostgreSQL. Uses **imperative mapping** so domain dataclasses stay ORM-free:

```python
# persistence/backends/sql/base.py
from sqlalchemy import MetaData, Table, Column, String, Text, JSON, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.orm import registry, relationship
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from agent_gateway.persistence.domain import (
    ExecutionRecord, ExecutionStep, AuditLogEntry, ScheduleRecord,
)

def build_metadata(table_prefix: str = "", schema: str | None = None) -> MetaData:
    """Build MetaData with naming convention, optional schema."""
    return MetaData(
        schema=schema,
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )

def build_tables(metadata: MetaData, prefix: str = "") -> dict[str, Table]:
    """Define all tables with optional prefix."""
    executions = Table(
        f"{prefix}executions", metadata,
        Column("id", String, primary_key=True),
        Column("agent_id", String, nullable=False),
        Column("status", String, nullable=False, default="queued"),
        Column("message", Text, nullable=False, default=""),
        Column("context", JSON),
        Column("options", JSON),
        Column("result", JSON),
        Column("error", Text),
        Column("usage", JSON),
        Column("started_at", DateTime),
        Column("completed_at", DateTime),
        Column("created_at", DateTime, nullable=False),
    )
    # ... execution_steps, audit_log, schedules tables
    return {"executions": executions, "execution_steps": ..., ...}

def configure_mappers(
    mapper_registry: registry,
    tables: dict[str, Table],
) -> None:
    """Wire SQLAlchemy to plain dataclasses via imperative mapping."""
    mapper_registry.map_imperatively(
        ExecutionRecord,
        tables["executions"],
        properties={
            "steps": relationship(ExecutionStep, back_populates="execution",
                                  cascade="all, delete-orphan"),
        },
    )
    # ... map ExecutionStep, AuditLogEntry, ScheduleRecord


class SqlBackend:
    """Base class for SQL persistence backends (not a Protocol — concrete shared logic)."""

    def __init__(
        self,
        engine: AsyncEngine,
        metadata: MetaData,
        mapper_registry: registry,
        tables: dict[str, Table],
    ) -> None:
        self._engine = engine
        self._metadata = metadata
        self._mapper_registry = mapper_registry
        self._tables = tables
        self._session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )
        configure_mappers(mapper_registry, tables)

    async def initialize(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all)

    async def dispose(self) -> None:
        self._mapper_registry.dispose()
        await self._engine.dispose()

    @property
    def execution_repo(self) -> ExecutionRepository:
        return self._execution_repo

    @property
    def audit_repo(self) -> AuditRepository:
        return self._audit_repo
```

#### SQLite Backend

**File:** `src/agent_gateway/persistence/backends/sqlite.py`

```python
# persistence/backends/sqlite.py
from agent_gateway.persistence.backends.sql.base import SqlBackend, build_metadata, build_tables

class SqliteBackend(SqlBackend):
    """SQLite persistence backend. Requires: pip install agent-gateway[sqlite]"""

    def __init__(
        self,
        path: str = "agent_gateway.db",
        table_prefix: str = "",
    ) -> None:
        try:
            import aiosqlite  # noqa: F401
        except ImportError:
            raise ImportError(
                "SQLite backend requires the sqlite extra: "
                "pip install agent-gateway[sqlite]"
            ) from None

        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.orm import registry

        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url, connect_args={"check_same_thread": False})
        metadata = build_metadata(table_prefix=table_prefix)
        mapper_reg = registry(metadata=metadata)
        tables = build_tables(metadata, prefix=table_prefix)

        super().__init__(engine, metadata, mapper_reg, tables)
```

#### PostgreSQL Backend

**File:** `src/agent_gateway/persistence/backends/postgres.py`

```python
# persistence/backends/postgres.py
from agent_gateway.persistence.backends.sql.base import SqlBackend, build_metadata, build_tables

class PostgresBackend(SqlBackend):
    """PostgreSQL persistence backend. Requires: pip install agent-gateway[postgres]"""

    def __init__(
        self,
        url: str,
        schema: str | None = None,
        table_prefix: str = "",
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> None:
        try:
            import asyncpg  # noqa: F401
        except ImportError:
            raise ImportError(
                "PostgreSQL backend requires the postgres extra: "
                "pip install agent-gateway[postgres]"
            ) from None

        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.orm import registry

        # Normalize DSN
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        engine = create_async_engine(url, pool_size=pool_size, max_overflow=max_overflow)
        metadata = build_metadata(table_prefix=table_prefix, schema=schema)
        mapper_reg = registry(metadata=metadata)
        tables = build_tables(metadata, prefix=table_prefix)

        super().__init__(engine, metadata, mapper_reg, tables)
```

### Gateway Fluent API

**Changes to:** `src/agent_gateway/gateway.py`

```python
class Gateway(FastAPI):
    def __init__(self, ...):
        # ...
        self._persistence_backend: PersistenceBackend | None = None
        self._execution_repo: ExecutionRepository = NullExecutionRepository()
        self._audit_repo: AuditRepository = NullAuditRepository()
        self._db_engine: AsyncEngine | None = None  # removed — managed by backend

    def use_sqlite(
        self,
        path: str = "agent_gateway.db",
        table_prefix: str = "",
    ) -> Gateway:
        """Configure SQLite persistence. Requires: pip install agent-gateway[sqlite]"""
        from agent_gateway.persistence.backends.sqlite import SqliteBackend
        self._persistence_backend = SqliteBackend(path=path, table_prefix=table_prefix)
        return self

    def use_postgres(
        self,
        url: str,
        schema: str | None = None,
        table_prefix: str = "",
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> Gateway:
        """Configure PostgreSQL persistence. Requires: pip install agent-gateway[postgres]"""
        from agent_gateway.persistence.backends.postgres import PostgresBackend
        self._persistence_backend = PostgresBackend(
            url=url, schema=schema, table_prefix=table_prefix,
            pool_size=pool_size, max_overflow=max_overflow,
        )
        return self

    def use_persistence(self, backend: PersistenceBackend | None) -> Gateway:
        """Configure a custom persistence backend, or None to disable."""
        self._persistence_backend = backend
        return self

    async def _startup(self) -> None:
        # ...
        # 5. Init persistence
        backend = self._persistence_backend
        if backend is None and self._config.persistence.enabled:
            # Fall back to YAML config (backward compat)
            backend = self._backend_from_config(self._config.persistence)

        if backend is not None:
            try:
                await backend.initialize()
                self._persistence_backend = backend
                self._execution_repo = backend.execution_repo
                self._audit_repo = backend.audit_repo
            except Exception:
                logger.warning("Failed to init persistence, using null repos", exc_info=True)

    def _backend_from_config(self, config: PersistenceConfig) -> PersistenceBackend | None:
        """Create a backend from YAML/env configuration (backward compat)."""
        if config.backend == "sqlite":
            from agent_gateway.persistence.backends.sqlite import SqliteBackend
            # Extract path from URL: "sqlite+aiosqlite:///foo.db" -> "foo.db"
            path = config.url.split("///", 1)[-1] if "///" in config.url else "agent_gateway.db"
            return SqliteBackend(
                path=path,
                table_prefix=config.table_prefix,
            )
        elif config.backend == "postgres":
            from agent_gateway.persistence.backends.postgres import PostgresBackend
            return PostgresBackend(
                url=config.url,
                schema=config.schema,
                table_prefix=config.table_prefix,
            )
        return None

    async def _shutdown(self) -> None:
        # ...
        if self._persistence_backend is not None:
            await self._persistence_backend.dispose()
```

### Updated PersistenceConfig

**File:** `src/agent_gateway/config.py`

```python
class PersistenceConfig(BaseModel):
    enabled: bool = True
    backend: str = "sqlite"           # sqlite | postgres
    url: str = "sqlite+aiosqlite:///agent_gateway.db"
    table_prefix: str = ""            # NEW: e.g. "ag_"
    schema: str | None = None         # NEW: PostgreSQL schema name
```

### Updated pyproject.toml Extras

```toml
[project]
dependencies = [
    # ... core deps, NO aiosqlite or asyncpg here
    "sqlalchemy>=2.0",
    # ...
]

[project.optional-dependencies]
sqlite = ["aiosqlite>=0.20"]
postgres = ["asyncpg>=0.29"]
postgresql = ["agent-gateway[postgres]"]  # alias for discoverability
dev = [
    # ... existing dev deps
    "aiosqlite>=0.20",   # dev always has SQLite for tests
]
all = ["agent-gateway[sqlite,postgres,otlp,slack,redis]"]
```

### File Structure After Refactor

```
src/agent_gateway/persistence/
    __init__.py
    domain.py              # NEW: plain dataclasses
    protocols.py           # UPDATED: imports from domain.py
    backend.py             # NEW: PersistenceBackend protocol
    null.py                # UPDATED: imports from domain.py
    backends/
        __init__.py
        sql/
            __init__.py
            base.py        # NEW: shared SQLAlchemy logic + imperative mapping
            repository.py  # MOVED+UPDATED: from persistence/repository.py
        sqlite.py          # NEW: SqliteBackend
        postgres.py        # NEW: PostgresBackend
    models.py              # DEPRECATED: kept temporarily for migration, re-exports from domain.py
    repository.py          # DEPRECATED: re-exports from backends/sql/repository.py
    session.py             # DEPRECATED: logic moved to backends/sql/base.py
```

### NoSQL Extension Point

A future MongoDB backend would look like:

```python
# persistence/backends/mongo.py (not in scope — illustrative)
from motor.motor_asyncio import AsyncIOMotorClient

class MongoBackend:
    def __init__(self, url: str, database: str = "agent_gateway"):
        self._client = AsyncIOMotorClient(url)
        self._db = self._client[database]

    async def initialize(self) -> None:
        # Create indexes
        await self._db.executions.create_index("agent_id")

    async def dispose(self) -> None:
        self._client.close()

    @property
    def execution_repo(self) -> ExecutionRepository:
        return MongoExecutionRepository(self._db)

    @property
    def audit_repo(self) -> AuditRepository:
        return MongoAuditRepository(self._db)

# Usage:
gw.use_persistence(MongoBackend("mongodb://localhost:27017"))
```

This works because `PersistenceBackend` is a Protocol (structural typing) — no inheritance required. And the repos work with plain dataclasses, not SQLAlchemy models.

### ERD

```mermaid
erDiagram
    EXECUTIONS {
        string id PK
        string agent_id
        string status
        text message
        json context
        json options
        json result
        text error
        json usage
        datetime started_at
        datetime completed_at
        datetime created_at
    }

    EXECUTION_STEPS {
        int id PK
        string execution_id FK
        string step_type
        int sequence
        json data
        int duration_ms
        datetime created_at
    }

    AUDIT_LOG {
        int id PK
        string event_type
        string actor
        string resource_type
        string resource_id
        json metadata
        string ip_address
        datetime created_at
    }

    SCHEDULES {
        string id PK
        string agent_id
        string name
        string cron_expr
        text message
        json context
        bool enabled
        string timezone
        datetime last_run_at
        datetime next_run_at
        datetime created_at
    }

    EXECUTIONS ||--o{ EXECUTION_STEPS : "has steps"
```

*Table names shown without prefix. With `table_prefix="ag_"`, they become `ag_executions`, `ag_execution_steps`, etc.*

## Implementation Phases

### Phase 1: Domain Dataclasses & Protocol Update

**Goal:** Decouple domain types from SQLAlchemy without breaking anything.

- [x] Create `persistence/domain.py` with plain `@dataclass` versions of all four models
- [x] Update `persistence/protocols.py` to import from `domain.py`
- [x] Update `persistence/null.py` to import from `domain.py`
- [x] Make `persistence/models.py` re-export from `domain.py` for backward compat (thin shim)
- [x] Update `api/routes/executions.py` and `api/routes/invoke.py` to import from `domain.py`
- [x] Update all tests importing from `persistence/models.py`
- [x] All existing tests pass

**Estimated files changed:** 6-8
**Risk:** Low — additive, backward compatible via re-exports

### Phase 2: Backend Abstraction & SQL Base

**Goal:** Introduce `PersistenceBackend` protocol and shared SQL infrastructure.

- [x] Create `persistence/backend.py` with `PersistenceBackend` protocol
- [x] Create `persistence/backends/sql/base.py` with imperative mapping, `build_metadata`, `build_tables`, `SqlBackend`
- [x] Move repository logic to `persistence/backends/sql/repository.py` (updated to work with imperative-mapped dataclasses)
- [x] Create `persistence/backends/sqlite.py` — `SqliteBackend`
- [x] Create `persistence/backends/postgres.py` — `PostgresBackend`
- [x] Write unit tests for `SqliteBackend` (create, read, update, list)
- [x] Write unit tests for `PostgresBackend` (same operations, requires running PG or skip)

**Estimated files changed:** 7 new files
**Risk:** Medium — imperative mapping is less common than declarative; needs careful testing

### Phase 3: Gateway Fluent API & Config Update

**Goal:** Wire the new backends into Gateway with the dream API.

- [x] Add `use_sqlite()`, `use_postgres()`, `use_persistence()` methods to `Gateway`
- [x] Add `_backend_from_config()` for YAML backward compatibility
- [x] Update `_startup()` to use `PersistenceBackend` instead of direct session creation
- [x] Update `_shutdown()` to call `backend.dispose()`
- [x] Add `table_prefix` and `schema` fields to `PersistenceConfig`
- [x] Remove `self._db_engine` field (now managed by backend)
- [x] Integration tests: `gw.use_sqlite()` then invoke
- [x] Integration tests: YAML config backward compat

**Estimated files changed:** 2-3 (gateway.py, config.py, tests)
**Risk:** Medium — changes Gateway startup sequence

### Phase 4: pyproject.toml & Cleanup

**Goal:** Move drivers to optional extras, clean up deprecated files.

- [x] Move `aiosqlite` from `dependencies` to `[sqlite]` extra
- [x] Rename `postgresql` extra to `postgres`, keep `postgresql` as alias
- [x] Add `aiosqlite` to `dev` extra so tests still work
- [x] Update `all` extra
- [x] Delete deprecated `persistence/session.py` (logic now in `backends/sql/base.py`)
- [x] Delete deprecated `persistence/repository.py` (logic now in `backends/sql/repository.py`)
- [x] Delete deprecated `persistence/models.py` (replaced by `domain.py` + imperative mapping)
- [x] Verify clean install with `pip install agent-gateway[sqlite]` and `pip install agent-gateway[postgres]`
- [x] Update any CI/CD configuration

**Estimated files changed:** 4-5
**Risk:** High — removing `aiosqlite` from core deps is a breaking change for users who don't specify extras. Mitigate with clear error messages.

## Design Decisions & Edge Cases

These decisions were surfaced by SpecFlow analysis of the user flows.

### D1: Precedence — Fluent API vs gateway.yaml

**Rule:** Fluent API (`gw.use_postgres(...)`) always wins over `gateway.yaml`. If no fluent call is made, fall back to YAML config. If neither is configured, use NullPersistence.

```
Fluent API call made?  →  Use fluent backend (ignore YAML persistence section)
No fluent call?        →  Read gateway.yaml persistence config
YAML persistence.enabled=false?  →  NullPersistence
YAML persistence.enabled=true?   →  Build backend from YAML config
No YAML file?          →  NullPersistence (default)
```

### D2: Timing — `use_*()` must be called before startup

`use_sqlite()`, `use_postgres()`, and `use_persistence()` store the backend instance on `self._persistence_backend` but do NOT call `initialize()`. Initialization happens in `_startup()`. Calling `use_*()` after startup raises `RuntimeError("Cannot configure persistence after gateway has started")`.

```python
def use_postgres(self, url: str, ...) -> Gateway:
    if self._started:
        raise RuntimeError("Cannot configure persistence after gateway has started")
    ...
```

### D3: Error handling — wrong extra installed

**Hard error, not silent fallback.** If the developer explicitly configures a backend (via fluent API or YAML), the gateway should raise `ImportError` at startup with a clear install command. The silent fallback to NullPersistence is only used when persistence is explicitly disabled or no config is provided.

```python
# In _startup():
if backend is not None:
    try:
        await backend.initialize()
        ...
    except ImportError:
        raise  # Don't swallow missing driver errors
    except Exception:
        logger.warning("Failed to init persistence, using null repos", exc_info=True)
```

The `ImportError` is raised inside the backend constructor (e.g., `SqliteBackend.__init__` checks `import aiosqlite`), so it surfaces before `initialize()` is even called.

### D4: Domain dataclasses are in the core package

`agent_gateway.persistence.domain` has **zero optional dependencies**. It is always importable with a base `pip install agent-gateway`. This is non-negotiable — protocols, null repos, and API routes all depend on it.

### D5: Field names are stable

The domain dataclass field names (`id`, `agent_id`, `status`, `message`, `context`, `options`, `result`, `error`, `usage`, `started_at`, `completed_at`, `created_at`) are identical to the current SQLAlchemy model attributes. No field renames. The `_record_to_response()` function in routes continues to work unchanged.

### D6: `ScheduleRecord` is in scope

All four models are included in the domain dataclasses and imperative mapping. The PostgreSQL-specific partial index (`postgresql_where="enabled = TRUE"`) is handled by SQLAlchemy's dialect-specific DDL — it's emitted only when the backend is PostgreSQL. For SQLite, a regular index is created instead.

### D7: `[postgresql]` extra renamed to `[postgres]`, old name kept as alias

```toml
postgres = ["asyncpg>=0.29"]
postgresql = ["agent-gateway[postgres]"]  # backward-compat alias
```

Existing `pip install agent-gateway[postgresql]` continues to work.

### D8: `use_sqlite(":memory:")` is supported

`:memory:` is a valid path argument. The backend translates it to `sqlite+aiosqlite:///:memory:`.

### D9: Existing database migration

`create_all` is idempotent — it creates tables that don't exist and skips tables that do. If a developer upgrades without changing `table_prefix`, their existing tables are reused as-is. If they add a `table_prefix`, new tables are created alongside old ones; old data is NOT migrated automatically. This is documented as a known limitation until Alembic migration support lands (v1.1+).

### D10: `gw.use_persistence(None)` explicitly disables persistence

Equivalent to `persistence.enabled: false`. Uses NullPersistence for both repos.

### D11: PostgreSQL schema must pre-exist

The gateway does NOT create PostgreSQL schemas. `schema="agent_gateway"` tells SQLAlchemy to qualify table names as `agent_gateway.executions`, but the developer must create the schema first via `CREATE SCHEMA agent_gateway`. If the schema doesn't exist, PostgreSQL raises an error at `create_all` time, which surfaces as a startup failure.

## Alternative Approaches Considered

### 1. Keep SQLAlchemy declarative models as the domain type
**Rejected:** Forces all consumers (including future NoSQL backends) to depend on SQLAlchemy. The whole point is backend independence.

### 2. Use ABC instead of Protocol for PersistenceBackend
**Rejected:** Protocol enables structural subtyping — a NoSQL backend doesn't need to inherit from anything. Better for a library.

### 3. Use SQLAlchemy's `schema_translate_map` for multi-tenant schema support
**Rejected:** Has known caching edge cases with compiled queries. Static `MetaData(schema=...)` is correct for single-tenant use cases.

### 4. Use SQLModel instead of plain dataclasses
**Rejected:** SQLModel is still SQLAlchemy under the hood. Adds a dependency without solving the NoSQL problem.

## Acceptance Criteria

### Functional Requirements

- [x] `gw.use_sqlite("dev.db")` configures SQLite persistence
- [x] `gw.use_postgres("postgresql+asyncpg://...")` configures PostgreSQL persistence
- [x] `gw.use_postgres(url, schema="myschema")` uses the specified PG schema
- [x] `gw.use_postgres(url, table_prefix="ag_")` prefixes all table names
- [x] `gw.use_sqlite(path, table_prefix="ag_")` prefixes all table names
- [x] `gw.use_persistence(None)` disables persistence (null repos)
- [x] `gw.use_persistence(CustomBackend())` works for any Protocol-compliant backend
- [x] YAML config `persistence.backend: sqlite` still works (backward compat)
- [x] YAML config `persistence.backend: postgres` still works
- [x] New YAML fields `table_prefix` and `schema` work
- [x] Missing driver gives clear `ImportError` with install instructions
- [x] All CRUD operations work: create, get, update_status, update_result, list_by_agent, add_step
- [x] Audit repo works: log, list_recent
- [x] NullPersistence still works when backend is None/disabled

### Non-Functional Requirements

- [x] Domain types (`persistence/domain.py`) have zero SQLAlchemy imports
- [x] Protocol types (`persistence/protocols.py`) have zero SQLAlchemy imports
- [x] NullPersistence (`persistence/null.py`) has zero SQLAlchemy imports
- [x] SQLAlchemy is only imported inside `backends/sql/` and when a SQL backend is selected
- [x] `pip install agent-gateway` (no extras) does not pull in `aiosqlite` or `asyncpg`
- [x] `pip install agent-gateway[sqlite]` pulls in `aiosqlite`
- [x] `pip install agent-gateway[postgres]` pulls in `asyncpg`

### Quality Gates

- [x] All existing persistence tests pass
- [x] New tests for SqliteBackend and PostgresBackend
- [x] New tests for fluent API (`use_sqlite`, `use_postgres`, `use_persistence`)
- [x] New tests for table prefix and schema
- [x] New tests for import error handling (missing extras)
- [x] Integration test: full invoke cycle with SQLite backend
- [x] mypy passes with `--strict`

## Dependencies & Prerequisites

- SQLAlchemy >= 2.0 (already a dependency — imperative mapping requires 2.0+)
- aiosqlite >= 0.20 (moves to optional extra)
- asyncpg >= 0.29 (already in `postgresql` extra)

## Risk Analysis & Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Imperative mapping has subtle differences from declarative | Medium | Medium | Thorough test coverage; test both create_all and round-trip CRUD |
| Removing aiosqlite from core deps breaks existing users | High | High | Clear ImportError message with install command; document in changelog |
| Multiple mapper registries (one per backend) cause conflicts | Medium | Low | Each backend creates its own `registry()` instance; never share |
| PostgreSQL schema creation requires `CREATE SCHEMA` privilege | Low | Medium | Document; `create_all` does NOT create schemas — users must create them first |
| Table prefix breaks existing databases on upgrade | Medium | Medium | Default prefix is `""` (no prefix); migration guide for users who want prefix |

## Future Considerations

- **Alembic migrations:** Once the imperative mapping is stable, Alembic can generate migrations from `MetaData`. The `table_prefix` and `schema` will be baked into the migration scripts.
- **MongoDB backend:** The `PersistenceBackend` protocol is designed for this. A `MongoBackend` would implement repos that serialize dataclasses to/from BSON documents.
- **Redis backend:** For ephemeral execution tracking (no audit). Would implement `ExecutionRepository` but `AuditRepository` could be null.
- **Connection pooling config:** The PostgreSQL backend accepts `pool_size` and `max_overflow`. Future: expose in YAML config.
- **Multi-tenant:** `schema_translate_map` could be revisited if multi-tenancy becomes a requirement. Current design uses static schema per deployment.

## References

### Internal References

- Current persistence models: `src/agent_gateway/persistence/models.py`
- Current protocols: `src/agent_gateway/persistence/protocols.py`
- Current repository: `src/agent_gateway/persistence/repository.py`
- Current session management: `src/agent_gateway/persistence/session.py`
- Gateway startup (persistence init): `src/agent_gateway/gateway.py:246-266`
- Routes using ExecutionRecord: `src/agent_gateway/api/routes/invoke.py:30`, `src/agent_gateway/api/routes/executions.py:14`
- Current PersistenceConfig: `src/agent_gateway/config.py:71-74`
- Current pyproject.toml extras: `pyproject.toml:47-65`

### External References

- [Architecture Patterns with Python — Repository Pattern](https://www.cosmicpython.com/book/chapter_02_repository.html)
- [SQLAlchemy 2.0 — Imperative Mapping](https://docs.sqlalchemy.org/en/20/orm/mapping_styles.html#imperative-mapping)
- [SQLAlchemy — MetaData schema and naming conventions](https://docs.sqlalchemy.org/en/20/core/metadata.html)
- [SQLAlchemy — Async session patterns](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Python Packaging — Optional Dependencies](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
