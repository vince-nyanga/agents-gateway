# CLAUDE.md

## Quick Reference

```bash
uv run pytest -m "not e2e"          # run tests (excludes e2e)
uv run pytest -m e2e -v             # run e2e tests (needs GEMINI_API_KEY)
uv run ruff check src/ tests/       # lint
uv run ruff format --check src/ tests/  # format check
uv run mypy src/                    # typecheck
make check                          # all of the above
```

Always use `uv run` — plain `python`/`pytest` won't resolve the package.

## Project Overview

Agent Gateway is a FastAPI extension for building API-first AI agent services. `Gateway` subclasses `FastAPI`. Agents, skills, and tools are defined as markdown files in a workspace directory.

## Project Structure

```
src/agent_gateway/
├── gateway.py          # Gateway class (extends FastAPI)
├── config.py           # Settings via pydantic-settings
├── exceptions.py       # Exception hierarchy (base: AgentGatewayError)
├── hooks.py            # Lifecycle hooks
├── api/                # Route handlers
├── auth/               # Auth backends (OAuth2, etc.)
├── chat/               # Chat/LLM integration
├── cli/                # Typer CLI
├── engine/             # Execution engine
├── notifications/      # Notification backends (slack, webhooks, etc.)
├── persistence/        # SQLAlchemy models & storage
├── queue/              # Message queue integration
├── scheduler/          # Cron scheduling (APScheduler)
├── telemetry/          # OpenTelemetry instrumentation
├── tools/              # Tool registration & execution
└── workspace/          # Workspace/agent loading from markdown
tests/                  # Mirrors src structure
examples/test-project/  # Example app (run with `make dev`)
```

## Key Conventions

- **Python 3.11+**, ruff for linting (line length 99), mypy strict mode
- **Exceptions**: always subclass `AgentGatewayError` from `exceptions.py`
- **Pending registration pattern**: store items in `_pending_*` dicts/lists, apply after workspace loads
- **Agents**: defined in `workspace/agents/<name>/` with `AGENT.md` + optional `BEHAVIOR.md`
- **Tests**: use `pytest-asyncio` (auto mode). Mark e2e tests with `@pytest.mark.e2e`, postgres tests with `@pytest.mark.postgres`, etc.

## Example Project

After every feature or fix, the example project in `examples/test-project/` MUST be updated to exercise the change. This is how we do real-life testing — run it with `make dev`. Do not consider a feature or fix complete until the example project demonstrates it.

## Documentation

After every feature or fix, the documentation in `docs/` MUST be updated to reflect the change. If a new feature is added, add or update the relevant guide in `docs/guides/`. If configuration changes, update `docs/guides/configuration.md` and `docs/api-reference/configuration.md`. If the public API changes, update `docs/api-reference/gateway.md`. Keep `docs/llms.txt` in sync for AI-friendly documentation access. Build docs locally with `uv run mkdocs serve`.

## Agent Workflow

Use the project's specialized agents to handle tasks. **Every step below is mandatory — never skip any agent.**

- **implementation-planner**: ALWAYS run first for any feature, fix, or refactor. Produces a structured implementation plan.
- **plan-reviewer**: ALWAYS run after planning, before writing any code. Validates the plan for architectural soundness, gaps, and best-practice violations. Do not proceed to implementation if the plan is rejected.
- **backend-implementer**: ALWAYS run after the plan is approved to implement backend code. Uses `/workflows:work`.
- **frontend-builder**: Run for any UI/frontend changes (in addition to or instead of backend-implementer).
- **code-reviewer**: ALWAYS run after implementation, before considering the task done. Runs `/workflows:review`. Do not mark a task complete or check it off without running this agent.

**Mandatory flow** (no steps may be skipped):
```
implementation-planner → plan-reviewer → [HUMAN APPROVAL] → backend-implementer and/or frontend-builder → code-reviewer
```

After `plan-reviewer` completes, **always present the plan to the user and wait for explicit approval before writing any code.** Do not proceed to implementation automatically.

## Pre-PR Checklist

Before creating any PR, always run:

```bash
uv run ruff format src/ tests/      # auto-format code
uv run ruff check src/ tests/       # lint
uv run mypy src/                    # typecheck
uv run pytest -m "not e2e" -x -q   # run tests
```

## Pre-Merge Workflow

Before merging any PR, always run `/workflows:review` to perform a multi-agent code review. Address all P1 (critical) findings before merging. P2/P3 findings can be tracked as follow-up work.

## Commit Messages

- No Co-Authored-By lines
- No mention of AI authorship
- Use conventional commit style (e.g. `feat:`, `fix:`, `refactor:`)
