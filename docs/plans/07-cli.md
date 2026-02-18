---
title: "Phase 1.7: CLI Commands"
type: feat
status: completed
date: 2026-02-18
depends_on: [01, 02]
blocks: [08]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.7: CLI Commands

## Goal

Implement the `agent-gateway` CLI with `init`, `serve`, `invoke`, `check`, `agents`, `skills`, and `schedules` commands. After this phase, developers can scaffold projects, start servers, and validate workspaces from the command line.

## Prerequisites

- Phase 01 (Typer stub)
- Phase 02 (workspace loader)

---

## Tasks

### 1. `agent-gateway init <project-name>`

**File:** `src/agent_gateway/cli/init_cmd.py`

Scaffold a new project:

- Create directory with name from argument
- Error if directory already exists (no `--force`)
- Create files:
  - `workspace/agents/assistant/AGENT.md` (default agent)
  - `workspace/agents/assistant/SOUL.md`
  - `workspace/gateway.yaml` (sensible defaults)
  - `app.py` (minimal Gateway setup)
  - `.env.example`
  - `.gitignore`
- Print success message with next steps

### 2. `agent-gateway serve`

**File:** `src/agent_gateway/cli/serve.py`

Start the gateway server:

- Options: `--host`, `--port`, `--reload`, `--workspace`
- Uses `uvicorn.run()` under the hood
- If `--reload`, pass it to uvicorn

### 3. `agent-gateway invoke <agent> "<message>"`

**File:** `src/agent_gateway/cli/invoke.py`

Invoke an agent from CLI:

- Load workspace
- Create Gateway instance
- Call `gw.invoke(agent_id, message)`
- Print result (formatted JSON)
- Options: `--workspace`, `--json` (raw JSON output)

### 4. `agent-gateway check`

**File:** `src/agent_gateway/cli/check.py`

Validate workspace:

- Load workspace via `WorkspaceLoader.load()`
- Print each agent/skill/tool with checkmark or cross
- Print warnings and errors
- Exit code 0 if no errors, 1 if errors
- Options: `--workspace`

### 5. `agent-gateway agents` / `skills` / `schedules`

**File:** `src/agent_gateway/cli/list_cmd.py`

List discovered resources:

- Load workspace
- Print table of agents (id, skills count, tools count)
- Print table of skills (id, description, tools)
- Print table of schedules (name, agent, cron, enabled, next run)

### 6. Wire into Main App

Update `src/agent_gateway/cli/main.py` to register all commands.

---

## Tests

- `init` creates correct file structure in tmp dir
- `check` validates fixture workspace correctly
- `check` reports errors for broken workspace
- All commands have `--help`

## Acceptance Criteria

- [x] `agent-gateway init test-project` creates correct scaffold
- [x] `agent-gateway check` validates workspace with proper output
- [x] `agent-gateway agents` lists discovered agents
- [x] All commands have help text
- [x] Exit codes are correct (0 success, 1 error)
