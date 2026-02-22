---
title: "Per-User Agent Configuration"
status: completed
priority: P0
category: Feature
date: 2026-02-22
---

# Per-User Agent Configuration

## Problem

In a corporate environment, a company may deploy an "email monitoring agent" but each employee needs to configure it for their own use — their own instructions (custom prompt), their own schedule ("check my inbox every morning"), and their own secrets (email credentials, API tokens). Today, agents are organization-wide only. There is no way for individual users to personalize an agent, provide their own credentials, or set up user-specific schedules. Without this, businesses can only deploy one-size-fits-all agents, which severely limits adoption.

## What Exists Today

- User identity flows through OAuth2 (`auth.subject` → `user_id`)
- `UserProfile` exists with extensible `metadata` dict
- Memory is already per-user scoped (60% user / 40% global split)
- `ToolContext` passes `caller_identity` to tool handlers
- Conversations are user-scoped
- `invoke()` route does NOT pass auth context (only `chat()` does)

## What's Missing

- Per-user agent configuration storage (instructions, settings, secrets)
- Agent scope model (global vs. individual)
- Per-user scheduling
- Secure secret storage for user credentials
- Setup/onboarding flow for individual agents
- Dashboard UI for users to configure their agents
- Prompt injection point for user-specific instructions

## Concepts

- **Agent scope**: Each agent in AGENT.md gets a new frontmatter field `scope: global | personal`. Global agents work as today. Personal agents require per-user configuration before use.
- **User agent config**: A new `UserAgentConfig` record stores per-user settings for an agent: custom instructions (prompt), configuration values, and encrypted secrets.
- **Setup schema**: Personal agents define a `setup_schema` in AGENT.md frontmatter — a JSON Schema describing what the user must provide (e.g., email server, credentials, preferences). Users cannot invoke the agent until setup is complete.
- **User secrets**: Sensitive fields in the setup schema are marked `"sensitive": true`. These are encrypted at rest using Fernet symmetric encryption (key from config/env). Never returned in API responses — only passed to tool handlers at execution time.
- **User instructions**: Each user can provide a custom prompt block that is injected into the system prompt as a dedicated layer (between agent prompt and memory).
- **User schedules**: Personal agents allow users to create their own cron schedules via API/dashboard, with their own input and cadence.

## Files to Change

**New files:**
- `src/agent_gateway/persistence/domain.py` — Add `UserAgentConfig` domain model
- `src/agent_gateway/persistence/backends/sql/repository.py` — Add `UserAgentConfigRepository`
- `src/agent_gateway/persistence/protocols.py` — Add repository protocol
- `src/agent_gateway/secrets.py` — Fernet encryption/decryption for user secrets
- `src/agent_gateway/api/routes/user_config.py` — CRUD API for user agent configuration
- `tests/test_user_config/` — Test directory

**Modified files:**
- `src/agent_gateway/workspace/agent.py` — Add `scope`, `setup_schema` to `AgentDefinition`
- `src/agent_gateway/workspace/prompt.py` — Add user instructions layer to `assemble_system_prompt()`
- `src/agent_gateway/gateway.py` — Load user config during invoke/chat, inject into prompt, pass secrets to tool context
- `src/agent_gateway/api/routes/invoke.py` — Pass auth context to `gw.invoke()` (fix existing gap)
- `src/agent_gateway/engine/models.py` — Add `user_secrets` to `ToolContext`
- `src/agent_gateway/scheduler/engine.py` — Support per-user schedules
- `src/agent_gateway/dashboard/router.py` — Add agent setup/config pages
- `src/agent_gateway/persistence/backends/sql/base.py` — Add new table mappings

## Plan

### Phase 1 — Data model & storage
1. Add `scope: str = "global"` and `setup_schema: dict | None = None` to `AgentDefinition` frontmatter parsing
2. Create `UserAgentConfig` domain model:
   ```
   user_id: str
   agent_id: str
   instructions: str | None          # user's custom prompt
   config_values: dict               # non-sensitive settings
   encrypted_secrets: dict            # Fernet-encrypted sensitive values
   setup_completed: bool              # has user completed required setup?
   created_at / updated_at: datetime
   ```
3. Create `user_agent_configs` table with composite PK `(user_id, agent_id)`, indexes on `user_id` and `agent_id`
4. Implement `UserAgentConfigRepository` with `get()`, `upsert()`, `delete()`, `list_by_user()`, `list_by_agent()`
5. Create `src/agent_gateway/secrets.py` with Fernet encryption:
   - `encrypt_value(plaintext, key)` → ciphertext
   - `decrypt_value(ciphertext, key)` → plaintext
   - Key sourced from `AGENT_GATEWAY_SECRET_KEY` env var (required for personal agents)
   - Sensitive fields identified by `"sensitive": true` in setup_schema properties

### Phase 2 — API layer
6. Create `POST /v1/agents/{agent_id}/config` — Save user's configuration for a personal agent
   - Validates against agent's `setup_schema`
   - Encrypts sensitive fields
   - Sets `setup_completed = true` once all required fields provided
7. Create `GET /v1/agents/{agent_id}/config` — Get user's config (secrets redacted to `"***"`)
8. Create `DELETE /v1/agents/{agent_id}/config` — Remove user's config
9. Create `GET /v1/agents/{agent_id}/setup-schema` — Get the setup schema for a personal agent
10. Add scope `agents:configure` for config CRUD operations
11. Fix `invoke()` route to pass `auth` context (parity with `chat()`)

### Phase 3 — Execution integration
12. In `Gateway.chat()` and `Gateway.invoke()`:
    - Load `UserAgentConfig` for the current user + agent
    - If agent is `personal` and `setup_completed == false`, return 409 with message "Agent setup required"
    - Pass decrypted secrets to `ToolContext` as `user_secrets: dict`
    - Pass user instructions to `assemble_system_prompt()`
13. Update `assemble_system_prompt()` to accept and inject `user_instructions: str | None` as a new layer after agent prompt but before memory
14. Update `ToolContext` to include `user_secrets: dict[str, str]` — tool handlers can access user credentials
15. Update `ToolContext` to include `user_config: dict` — tool handlers can access non-sensitive user settings

### Phase 4 — Per-user schedules
16. Create `UserSchedule` domain model:
    ```
    schedule_id: str
    user_id: str
    agent_id: str
    cron_expression: str
    timezone: str
    message: str
    input: dict | None
    enabled: bool
    ```
17. Add `user_schedules` table with FK to users
18. Add API endpoints:
    - `POST /v1/agents/{agent_id}/schedules` — Create user schedule
    - `GET /v1/agents/{agent_id}/schedules` — List user's schedules
    - `DELETE /v1/agents/{agent_id}/schedules/{schedule_id}` — Delete
    - `PATCH /v1/agents/{agent_id}/schedules/{schedule_id}` — Pause/resume/update
19. Update `SchedulerEngine` to register user schedules with APScheduler, passing `user_id` so execution runs with user's config and secrets

### Phase 5 — Dashboard UI
20. Add "My Agents" page — shows personal agents the user has configured + unconfigured ones
21. Add "Setup Agent" page — renders a form from the agent's `setup_schema`, with password fields for sensitive values
22. Add "My Schedules" page — CRUD for user-specific schedules
23. Show setup status badges on agent cards ("Configured" / "Setup Required")
24. Add admin view to see all user configurations for an agent (secrets still redacted)

### Phase 6 — Testing & example
25. Unit tests for encryption, config CRUD, setup validation, prompt injection
26. Integration tests for the full flow: setup → invoke → secrets available to tools
27. Update example project with a personal agent (e.g., "daily-briefing" agent requiring email config)

## AGENT.md Example

```yaml
---
description: Monitors your email and summarizes important messages
scope: personal
setup_schema:
  type: object
  required: [email_server, email_address, email_password]
  properties:
    email_server:
      type: string
      description: IMAP server address (e.g. imap.gmail.com)
    email_address:
      type: string
      description: Your email address
    email_password:
      type: string
      description: Your email password or app-specific password
      sensitive: true
    check_folders:
      type: array
      items:
        type: string
      default: ["INBOX"]
      description: Which folders to monitor
    summary_style:
      type: string
      enum: [brief, detailed]
      default: brief
      description: How detailed should the summaries be
schedules:
  - name: morning-check
    cron: "0 8 * * 1-5"
    message: "Check my email and summarize anything important"
    user_scheduled: true
---
You are an email monitoring assistant. Check the user's email...
```
