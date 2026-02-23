# Backend Implementer Memory

## Project Architecture
- `Gateway` subclasses FastAPI. Config is `_config` (private), not `config`
- Tool registration: `CodeTool` registered on `ToolRegistry` with optional `allowed_agents`
- Tool execution: `execute_code_tool` injects `context: ToolContext` if param named `context` exists in fn signature
- Execution records created by callers (API routes, scheduler), NOT by `gateway.invoke()`
- `_snapshot` holds `WorkspaceState`, `ToolRegistry`, `ExecutionEngine`

## Key Patterns
- **Pending registration**: `_pending_tools`, `_pending_retrievers`, etc. applied during `_startup()`
- **Null repos**: Must implement all Protocol methods. Check `NullExecutionRepository` when adding new methods
- **Migrations**: Numbered sequentially (001, 002...). Update `test_migrations.py` revision assertions
- **Domain dataclasses**: ORM-free in `persistence/domain.py`, mapped imperatively in `backends/sql/base.py`
- **Memory tools pattern**: Closure captures manager, registered as CodeTool with `allowed_agents` scoping

## File Locations
- Domain models: `src/agent_gateway/persistence/domain.py`
- SQL tables: `src/agent_gateway/persistence/backends/sql/base.py` (`build_tables`)
- SQL repos: `src/agent_gateway/persistence/backends/sql/repository.py`
- Protocols: `src/agent_gateway/persistence/protocols.py`
- Null repos: `src/agent_gateway/persistence/null.py`
- Agent parsing: `src/agent_gateway/workspace/agent.py`
- Tool registry: `src/agent_gateway/workspace/registry.py`
- Tool runner: `src/agent_gateway/tools/runner.py` + `function.py`
- Engine models: `src/agent_gateway/engine/models.py` (ToolContext, ExecutionOptions, etc.)
- Migrations: `src/agent_gateway/persistence/migrations/versions/`
- Dashboard templates: `src/agent_gateway/dashboard/templates/dashboard/`

## Pre-existing Issues (don't try to fix unless asked)
- `NullExecutionRepository` missing `get_summary_stats` (mypy error at gateway.py:121)
- Dashboard router.py:1061/1063 type annotation mismatch (float vs int)
- Dashboard router.py:537 unused variable `session` (ruff F841)

## Test Conventions
- Engine test fixtures in `tests/test_engine/conftest.py`
- `make_agent()`, `make_workspace()`, `make_engine()` helpers
- Migration tests assert revision number - update when adding migrations
- SQLite test DB file `agent_gateway.db` may be left over - delete if tests fail on schema mismatch
