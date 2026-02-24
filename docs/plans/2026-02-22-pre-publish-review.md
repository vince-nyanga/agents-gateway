# Pre-Publish Review: Agent Gateway

**Date:** 2026-02-22
**Goal:** Identify and plan all work needed before publishing agent-gateway as a Python package, enabling businesses to quickly spin up AI agent services.

---

## Summary of Findings

After a thorough review of the entire codebase, here are all items that need addressing, organized by priority.

### P0 — Must Fix Before Publish

- [x] **#1** [Conversation tracing & cost tracking](publish/01-conversation-tracing.md) — Bug/UX
- [x] **#2** [Database migration strategy](publish/02-database-migrations.md) — Infrastructure
- [x] **#3** [README & PyPI landing page](publish/03-readme.md) — Documentation
- [x] **#4** [Version management (build pipeline)](publish/04-version-management.md) — Packaging
- [x] **#5** [CORS middleware](publish/05-cors-middleware.md) — Security
- [x] **#6** [User-facing documentation](publish/06-documentation.md) — Documentation
- [x] **#7** [Per-user agent configuration](publish/07-per-user-agent-config.md) — Feature

### P1 — Should Fix Before Publish

- [x] **#8** [Agent-to-agent communication & handover](publish/08-agent-to-agent-communication.md) — Feature
- [x] **#9** [Rate limiting](publish/09-rate-limiting.md) — Security
- [x] **#10** [Security headers middleware](publish/10-security-headers.md) — Security
- [x] **#11** [OpenAPI endpoint documentation](publish/11-openapi-docs.md) — API
- [x] **#12** [Configuration reference docs](publish/12-config-reference-docs.md) — Documentation
- [x] **#13** [API route unit tests](publish/13-api-route-tests.md) — Testing
- [x] **#14** [PyPI publish workflow](publish/14-pypi-publish-workflow.md) — CI/CD
- [x] **#15** [Package metadata completeness](publish/15-package-metadata.md) — Packaging

### P2 — Should Fix Before GA

- [x] **#16** [Dashboard filtering & real-time updates](publish/16-dashboard-filtering.md) — UX
- [ ] **#17** [Distributed scheduler locking](publish/17-distributed-scheduler-locking.md) — Infrastructure
- [ ] **#18** [CLI output formats](publish/18-cli-output-formats.md) — DX
- [ ] **#19** [Streaming engine tests](publish/19-streaming-tests.md) — Testing
- [ ] **#20** [Dashboard test coverage](publish/20-dashboard-tests.md) — Testing
- [ ] **#21** [Notification delivery confirmation](publish/21-notification-delivery.md) — Reliability
- [ ] **#22** [Session persistence](publish/22-session-persistence.md) — Infrastructure
- [ ] **#23** [Missing database indexes](publish/23-missing-indexes.md) — Performance

---

## Detailed Plans

---

### 1. Conversation Tracing & Cost Tracking

**Problem:** Each chat turn creates a separate `execution_id`. On the dashboard, executions appear as isolated traces, making it impossible to view a full conversation's execution history or calculate total conversation cost.

**Root Cause:** The `executions` table has no `conversation_id` / `session_id` foreign key. Each call to `gateway.chat()` generates a new `uuid4()` execution ID with no link back to the conversation.

**Files to change:**
- `src/agent_gateway/persistence/domain.py` — Add `session_id` column to `ExecutionRecord`
- `src/agent_gateway/persistence/backends/sql/base.py` — Update table mapping, add FK + index
- `src/agent_gateway/gateway.py` — Pass `session_id` when creating execution records in `chat()`
- `src/agent_gateway/persistence/backends/sql/repository.py` — Add `list_by_session()`, aggregate cost queries by session
- `src/agent_gateway/api/routes/executions.py` — Add `?session_id=` filter parameter
- `src/agent_gateway/dashboard/router.py` — Group executions by conversation on detail page, show total conversation cost
- `src/agent_gateway/dashboard/models.py` — Add `ConversationDetail` view model with aggregated stats

**Plan:**
1. Add `session_id: str | None` field to `ExecutionRecord` domain model
2. Update SQL table mapping with nullable FK to `conversations` table + index on `session_id`
3. In `gateway.chat()`, pass the `session_id` to `_persist_execution()` so each chat turn's execution links to its conversation
4. Add `ExecutionRepository.list_by_session(session_id)` and `cost_by_session(session_id)` queries
5. Add `?session_id=` query parameter to `GET /v1/executions` endpoint
6. Update dashboard execution detail to show conversation context — link to related executions, show cumulative cost/tokens
7. Update dashboard conversation view to show total cost, token count, and execution count per conversation
8. Add tests for new queries and API parameters
9. Update example project to demonstrate conversation cost tracking

---

### 2. Database Migration Strategy

**Problem:** Currently uses `metadata.create_all()` which only creates new tables/columns. Cannot handle column renames, type changes, constraint modifications, or data migrations. Users upgrading the library will have no way to evolve their schema.

**Files to change:**
- `pyproject.toml` — Add `alembic` dependency
- `src/agent_gateway/persistence/migrations/` — New directory with Alembic config
- `src/agent_gateway/persistence/backends/sql/base.py` — Replace `create_all()` with Alembic runner
- `src/agent_gateway/cli/main.py` — Add `agent-gateway db upgrade` / `db downgrade` commands

**Plan:**
1. Add `alembic` as a core dependency in `pyproject.toml`
2. Create `src/agent_gateway/persistence/migrations/` with:
   - `alembic.ini` template (shipped with the package)
   - `env.py` configured to use the user's `persistence.url` from gateway config
   - `versions/` directory with initial migration creating all current tables
3. Update `SqlBackendBase.initialize()` to run Alembic `upgrade head` instead of `create_all()`
4. Add CLI commands:
   - `agent-gateway db upgrade [revision]` — Apply migrations
   - `agent-gateway db downgrade [revision]` — Roll back migrations
   - `agent-gateway db current` — Show current schema version
   - `agent-gateway db history` — Show migration history
5. Create the initial migration script capturing the current schema as baseline
6. Document the migration workflow in user docs (new installs auto-migrate; upgrades require `agent-gateway db upgrade`)
7. Add tests for migration up/down paths
8. Update example project README with migration instructions

---

### 3. README & PyPI Landing Page

**Problem:** Current README is 6 lines — just a title, badges, and one-liner. The excellent documentation in `examples/test-project/README.md` is buried and invisible to PyPI visitors. A business evaluating the library has no way to understand its value proposition.

**Files to change:**
- `README.md` — Complete rewrite

**Plan:**
1. Write a compelling README with these sections:
   - **Tagline & badges** (PyPI version, Python versions, license, CI, coverage)
   - **What is Agent Gateway?** — 2-3 sentence value prop for businesses
   - **Features** — Bullet list: markdown-defined agents, multi-LLM support, built-in auth, dashboard, scheduling, notifications, queue-based async, telemetry, structured output, memory
   - **Quick Start** — `pip install agent-gateway` → `agent-gateway init myproject` → `agent-gateway serve` (3 commands to hello world)
   - **Define an Agent** — Show AGENT.md example
   - **Add a Tool** — Show TOOL.md + handler.py example
   - **Configuration** — Show minimal `gateway.yaml`
   - **Dashboard** — Screenshot + brief description
   - **Documentation** — Link to docs site
   - **License** — MIT
2. Add a screenshot of the dashboard to `docs/assets/` and reference in README
3. Ensure all badge URLs point to the correct repository (not personal GitHub)

---

### 4. Version Management (Build Pipeline)

**Problem:** `pyproject.toml` has `version = "0.0.0"` with a comment about GitVersion replacement, but no build hook actually injects the version. `__init__.py` also hardcodes `"0.0.0"`. Published packages would show version 0.0.0.

**Files to change:**
- `pyproject.toml` — Configure dynamic versioning or build hook
- `src/agent_gateway/__init__.py` — Read version dynamically
- `.github/workflows/ci.yml` — Inject version at build/publish time

**Plan:**
1. Option A (recommended): Use `hatch-vcs` or `setuptools-scm` to derive version from git tags
   - Add `[tool.hatch.version]` with `source = "vcs"` in pyproject.toml
   - Change `version` field to dynamic: `dynamic = ["version"]`
   - Update `__init__.py` to use `importlib.metadata.version("agent-gateway")`
2. Option B: Keep GitVersion but add a CI step that writes the computed version into `pyproject.toml` before building
3. Verify version appears correctly in `pip show agent-gateway` and `agent-gateway --version`
4. Test the build locally with `uv build` and inspect the resulting wheel metadata

---

### 5. CORS Middleware

**Problem:** No CORS middleware configured. Browser-based clients (dashboards, SPAs, chatbots) will fail with CORS errors when calling the API. This is critical for businesses integrating agent-gateway into web applications.

**Files to change:**
- `src/agent_gateway/config.py` — Add `CorsConfig` model
- `src/agent_gateway/gateway.py` — Add CORS middleware during startup
- `tests/test_integration/test_cors.py` — New test file

**Plan:**
1. Add `CorsConfig` to config.py:
   ```python
   class CorsConfig(BaseModel):
       enabled: bool = False
       allow_origins: list[str] = ["*"]
       allow_methods: list[str] = ["GET", "POST", "DELETE", "OPTIONS"]
       allow_headers: list[str] = ["Authorization", "Content-Type"]
       max_age: int = 3600
   ```
2. Add `cors: CorsConfig` to `GatewayConfig`
3. In `Gateway.__aenter__()`, add `CORSMiddleware` from Starlette if `cors.enabled`
4. Add a convenience method `gw.use_cors(allow_origins=["..."])` for programmatic configuration
5. Add tests verifying CORS headers on preflight and actual requests
6. Update example project to enable CORS
7. Document in configuration reference

---

### 6. User-Facing Documentation

**Problem:** No documentation site exists. No getting started guide, no API reference, no configuration guide, no integration guides. Businesses cannot evaluate or adopt the library without documentation.

**Files to change:**
- `docs/` — New documentation structure
- `pyproject.toml` — Add docs dependencies (mkdocs)
- `mkdocs.yml` — New file

**Plan:**
1. Set up MkDocs with Material theme (`mkdocs-material`)
2. Create documentation structure:
   ```
   docs/
     index.md                    # Landing page
     getting-started/
       installation.md           # pip install, extras, requirements
       quickstart.md             # First agent in 5 minutes
       project-structure.md      # Workspace layout explained
     guides/
       agents.md                 # Defining agents with AGENT.md
       tools.md                  # File-based and code-based tools
       skills.md                 # Composable workflows
       configuration.md          # gateway.yaml reference
       authentication.md         # API keys, OAuth2, scopes
       persistence.md            # SQLite, PostgreSQL setup
       notifications.md          # Slack, webhooks
       scheduling.md             # Cron schedules
       memory.md                 # Agent memory system
       queue.md                  # Redis, RabbitMQ async execution
       telemetry.md              # OpenTelemetry setup
       dashboard.md              # Dashboard features, auth, theming
       context-retrieval.md      # RAG integration
       structured-output.md      # Input/output schemas
     api-reference/
       gateway.md                # Gateway class API
       configuration.md          # All config classes
       hooks.md                  # Lifecycle hooks
       exceptions.md             # Exception hierarchy
     deployment/
       production.md             # Production deployment checklist
       docker.md                 # Docker/compose setup
     changelog.md                # Version history
   ```
3. Write each page (can be iterative — start with getting-started + guides for core features)
4. Add `mkdocs.yml` with navigation, theme config, and plugins
5. Add GitHub Actions workflow to deploy docs to GitHub Pages
6. Link docs site from README

---

### 7. Per-User Agent Configuration

**Problem:** In a corporate environment, a company may deploy an "email monitoring agent" but each employee needs to configure it for their own use — their own instructions (custom prompt), their own schedule ("check my inbox every morning"), and their own secrets (email credentials, API tokens). Today, agents are organization-wide only. There is no way for individual users to personalize an agent, provide their own credentials, or set up user-specific schedules. Without this, businesses can only deploy one-size-fits-all agents, which severely limits adoption.

**What exists today:**
- User identity flows through OAuth2 (`auth.subject` → `user_id`)
- `UserProfile` exists with extensible `metadata` dict
- Memory is already per-user scoped (60% user / 40% global split)
- `ToolContext` passes `caller_identity` to tool handlers
- Conversations are user-scoped
- `invoke()` route does NOT pass auth context (only `chat()` does)

**What's missing:**
- Per-user agent configuration storage (instructions, settings, secrets)
- Agent scope model (global vs. individual)
- Per-user scheduling
- Secure secret storage for user credentials
- Setup/onboarding flow for individual agents
- Dashboard UI for users to configure their agents
- Prompt injection point for user-specific instructions

**Concepts:**

- **Agent scope**: Each agent in AGENT.md gets a new frontmatter field `scope: global | personal`. Global agents work as today. Personal agents require per-user configuration before use.
- **User agent config**: A new `UserAgentConfig` record stores per-user settings for an agent: custom instructions (prompt), configuration values, and encrypted secrets.
- **Setup schema**: Personal agents define a `setup_schema` in AGENT.md frontmatter — a JSON Schema describing what the user must provide (e.g., email server, credentials, preferences). Users cannot invoke the agent until setup is complete.
- **User secrets**: Sensitive fields in the setup schema are marked `"sensitive": true`. These are encrypted at rest using Fernet symmetric encryption (key from config/env). Never returned in API responses — only passed to tool handlers at execution time.
- **User instructions**: Each user can provide a custom prompt block that is injected into the system prompt as a dedicated layer (between agent prompt and memory).
- **User schedules**: Personal agents allow users to create their own cron schedules via API/dashboard, with their own input and cadence.

**Files to change:**

*New files:*
- `src/agent_gateway/persistence/domain.py` — Add `UserAgentConfig` domain model
- `src/agent_gateway/persistence/backends/sql/repository.py` — Add `UserAgentConfigRepository`
- `src/agent_gateway/persistence/protocols.py` — Add repository protocol
- `src/agent_gateway/secrets.py` — Fernet encryption/decryption for user secrets
- `src/agent_gateway/api/routes/user_config.py` — CRUD API for user agent configuration
- `tests/test_user_config/` — Test directory

*Modified files:*
- `src/agent_gateway/workspace/agent.py` — Add `scope`, `setup_schema` to `AgentDefinition`
- `src/agent_gateway/workspace/prompt.py` — Add user instructions layer to `assemble_system_prompt()`
- `src/agent_gateway/gateway.py` — Load user config during invoke/chat, inject into prompt, pass secrets to tool context
- `src/agent_gateway/api/routes/invoke.py` — Pass auth context to `gw.invoke()` (fix existing gap)
- `src/agent_gateway/engine/models.py` — Add `user_secrets` to `ToolContext`
- `src/agent_gateway/scheduler/engine.py` — Support per-user schedules
- `src/agent_gateway/dashboard/router.py` — Add agent setup/config pages
- `src/agent_gateway/persistence/backends/sql/base.py` — Add new table mappings

**Plan:**

**Phase 1 — Data model & storage:**
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

**Phase 2 — API layer:**
6. Create `POST /v1/agents/{agent_id}/config` — Save user's configuration for a personal agent
   - Validates against agent's `setup_schema`
   - Encrypts sensitive fields
   - Sets `setup_completed = true` once all required fields provided
7. Create `GET /v1/agents/{agent_id}/config` — Get user's config (secrets redacted to `"***"`)
8. Create `DELETE /v1/agents/{agent_id}/config` — Remove user's config
9. Create `GET /v1/agents/{agent_id}/setup-schema` — Get the setup schema for a personal agent
10. Add scope `agents:configure` for config CRUD operations
11. Fix `invoke()` route to pass `auth` context (parity with `chat()`)

**Phase 3 — Execution integration:**
12. In `Gateway.chat()` and `Gateway.invoke()`:
    - Load `UserAgentConfig` for the current user + agent
    - If agent is `personal` and `setup_completed == false`, return 409 with message "Agent setup required"
    - Pass decrypted secrets to `ToolContext` as `user_secrets: dict`
    - Pass user instructions to `assemble_system_prompt()`
13. Update `assemble_system_prompt()` to accept and inject `user_instructions: str | None` as a new layer after agent prompt but before memory
14. Update `ToolContext` to include `user_secrets: dict[str, str]` — tool handlers can access user credentials
15. Update `ToolContext` to include `user_config: dict` — tool handlers can access non-sensitive user settings

**Phase 4 — Per-user schedules:**
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

**Phase 5 — Dashboard UI:**
20. Add "My Agents" page — shows personal agents the user has configured + unconfigured ones
21. Add "Setup Agent" page — renders a form from the agent's `setup_schema`, with password fields for sensitive values
22. Add "My Schedules" page — CRUD for user-specific schedules
23. Show setup status badges on agent cards ("Configured" / "Setup Required")
24. Add admin view to see all user configurations for an agent (secrets still redacted)

**Phase 6 — Testing & example:**
25. Unit tests for encryption, config CRUD, setup validation, prompt injection
26. Integration tests for the full flow: setup → invoke → secrets available to tools
27. Update example project with a personal agent (e.g., "daily-briefing" agent requiring email config)

**AGENT.md example for a personal agent:**
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
    user_scheduled: true  # users can customize this schedule
---
You are an email monitoring assistant. Check the user's email...
```

---

### 8. Agent-to-Agent Communication & Handover

**Problem:** Agents operate in isolation. There is no way for one agent to delegate work to another agent, pass results, or orchestrate multi-agent workflows. In real business scenarios, a "research agent" might need to hand results to an "analysis agent" which then passes to a "report writer agent." The entire chain must be traceable as a single workflow with full cost visibility.

**What exists today:**
- Skills can compose multiple tools in a workflow (sequential + parallel steps)
- ExecutionRecord tracks individual agent runs with execution_id
- Tools receive `ToolContext` with execution_id and agent_id
- No concept of one agent invoking another

**Concepts:**

- **Agent delegation**: An agent can call another agent as if it were a tool — via a built-in `delegate_to_agent` tool that is automatically available when configured
- **Delegation chain**: Each delegation creates a child execution linked to the parent via `parent_execution_id`, forming a tree of executions
- **Workflow tracing**: The root execution_id is carried through the entire chain as `root_execution_id`, so the full workflow can be queried as a unit
- **Cost rollup**: Total cost for a workflow = sum of all executions sharing the same `root_execution_id`
- **Delegation policy**: Agents declare which other agents they can delegate to in AGENT.md frontmatter (`delegates_to: [agent-a, agent-b]`), preventing unbounded chains
- **Max depth**: A configurable guardrail limits delegation depth (default: 3) to prevent infinite loops

**Files to change:**

*New files:*
- `src/agent_gateway/engine/delegation.py` — Delegation tool implementation
- `tests/test_engine/test_delegation.py` — Delegation tests

*Modified files:*
- `src/agent_gateway/persistence/domain.py` — Add `parent_execution_id`, `root_execution_id` to `ExecutionRecord`
- `src/agent_gateway/persistence/backends/sql/base.py` — Update table mapping + indexes
- `src/agent_gateway/persistence/backends/sql/repository.py` — Add `list_by_root_execution()`, `cost_by_root_execution()`
- `src/agent_gateway/workspace/agent.py` — Add `delegates_to` to `AgentDefinition`
- `src/agent_gateway/gateway.py` — Wire delegation tool, pass parent/root IDs
- `src/agent_gateway/engine/executor.py` — Pass delegation context through execution
- `src/agent_gateway/engine/models.py` — Add delegation fields to `ToolContext`
- `src/agent_gateway/api/routes/executions.py` — Add `?root_execution_id=` filter, workflow view
- `src/agent_gateway/dashboard/router.py` — Workflow trace view showing delegation tree
- `src/agent_gateway/config.py` — Add `max_delegation_depth` to guardrails

**Plan:**

**Phase 1 — Execution lineage model:**
1. Add fields to `ExecutionRecord`:
   ```
   parent_execution_id: str | None   # direct parent (who delegated to me)
   root_execution_id: str | None     # root of the entire workflow tree
   delegation_depth: int = 0         # depth in the delegation tree
   ```
2. Add indexes on `parent_execution_id` and `root_execution_id`
3. Add `delegates_to: list[str] = []` to `AgentDefinition` frontmatter parsing
4. Add `max_delegation_depth: int = 3` to `GuardrailsConfig`

**Phase 2 — Delegation tool:**
5. Create `DelegationTool` — a built-in code tool automatically registered when an agent has `delegates_to` configured:
   ```
   name: "delegate_to_agent"
   description: "Delegate a task to another agent and get their result"
   parameters:
     agent_id: str      # which agent to delegate to (must be in delegates_to list)
     message: str       # the task/instruction for the target agent
     input: dict | None # optional structured input
   ```
6. Implementation calls `Gateway.invoke()` internally with:
   - `parent_execution_id` = current execution_id
   - `root_execution_id` = current root_execution_id (or current execution_id if this is the root)
   - `delegation_depth` = current depth + 1
   - Same `user_id` / auth context propagated
7. Guardrail check: if `delegation_depth >= max_delegation_depth`, return error to the calling agent
8. Permission check: if target `agent_id` not in caller's `delegates_to`, return error
9. Return the delegated agent's result as the tool result (truncated to 32KB like other tool results)

**Phase 3 — Tracing & cost rollup:**
10. Add `ExecutionRepository.list_by_root_execution(root_execution_id)` — returns all executions in a workflow tree
11. Add `ExecutionRepository.cost_by_root_execution(root_execution_id)` — aggregated cost across the tree
12. Add `GET /v1/executions/{execution_id}/workflow` — returns the full execution tree with relationships
13. Add `?root_execution_id=` filter to `GET /v1/executions`

**Phase 4 — Dashboard visualization:**
14. Add workflow trace view to execution detail page:
    - Tree visualization showing delegation chain (parent → children)
    - Each node shows: agent_id, status, duration, cost, input/output summary
    - Total workflow cost, total duration, total tokens at the top
15. Link parent/child executions bidirectionally in the execution detail page
16. Add "Workflow" badge on executions that are part of a delegation chain

**Phase 5 — Testing & example:**
17. Unit tests: delegation tool, depth limits, permission checks, execution lineage queries
18. Integration tests: A → B → C delegation chain with full tracing
19. Update example project with a multi-agent workflow (e.g., "research" → "analyze" → "report")

**AGENT.md example:**
```yaml
---
description: Orchestrates research tasks by delegating to specialists
delegates_to:
  - web-researcher
  - data-analyst
  - report-writer
---
You are a research coordinator. Break complex research tasks into parts
and delegate to specialist agents...
```

---

### 9. Rate Limiting

**Problem:** No rate limiting on any endpoint. A single client can overwhelm the service with requests, and auth endpoints are vulnerable to brute-force attacks. Businesses running this in production need basic protection.

**Files to change:**
- `pyproject.toml` — Add `slowapi` as optional dependency
- `src/agent_gateway/config.py` — Add `RateLimitConfig`
- `src/agent_gateway/gateway.py` — Add rate limiting middleware
- `tests/test_integration/test_rate_limiting.py` — New test file

**Plan:**
1. Add `slowapi` as optional dependency under a `[rate-limiting]` extra and include in `[all]`
2. Add `RateLimitConfig` with sensible defaults:
   - `enabled: bool = False`
   - `default_limit: str = "100/minute"` (per IP)
   - `auth_limit: str = "10/minute"` (for auth-related endpoints)
3. Integrate `slowapi` Limiter in Gateway startup when enabled
4. Apply stricter limits to auth-sensitive paths
5. Add `429 Too Many Requests` response documentation
6. Add tests verifying rate limit enforcement and headers
7. Document configuration options

---

### 10. Security Headers Middleware

**Problem:** No security headers (X-Content-Type-Options, X-Frame-Options, Content-Security-Policy, etc.). Browsers won't have basic protections against XSS, clickjacking, or MIME-sniffing attacks.

**Files to change:**
- `src/agent_gateway/api/middleware/security.py` — New middleware
- `src/agent_gateway/gateway.py` — Register middleware
- `tests/test_integration/test_security_headers.py` — New test file

**Plan:**
1. Create `SecurityHeadersMiddleware` (pure ASGI, same pattern as `AuthMiddleware`):
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (configurable)
   - `Content-Security-Policy: default-src 'self'` (configurable, relaxed for dashboard)
   - `Referrer-Policy: strict-origin-when-cross-origin`
2. Add to Gateway startup (applied to all responses)
3. Make configurable via `SecurityConfig` in config.py (opt-out, not opt-in)
4. Add tests verifying headers on API and dashboard responses
5. Document in deployment guide

---

### 11. OpenAPI Endpoint Documentation

**Problem:** Swagger UI at `/docs` shows endpoints but lacks descriptions, examples, response schemas, and scope requirements. Businesses evaluating the API have a poor experience in the interactive docs.

**Files to change:**
- `src/agent_gateway/api/routes/invoke.py`
- `src/agent_gateway/api/routes/chat.py`
- `src/agent_gateway/api/routes/executions.py`
- `src/agent_gateway/api/routes/introspection.py`
- `src/agent_gateway/api/routes/schedules.py`
- `src/agent_gateway/api/routes/health.py`
- `src/agent_gateway/api/routes/status.py`
- `src/agent_gateway/api/models.py`

**Plan:**
1. Add `summary`, `description`, `tags`, and `responses` to every route decorator
2. Add `Field(description=..., examples=[...])` to all Pydantic request/response models
3. Add `response_model` to all endpoints for auto-generated response docs
4. Group endpoints with tags: "Agents", "Executions", "Sessions", "Schedules", "Admin"
5. Add 401/403/404/422/429 response schemas to all protected endpoints
6. Verify the generated OpenAPI spec is complete and accurate

---

### 12. Configuration Reference Docs

**Problem:** 20+ configuration classes with no documentation. Users have no way to discover available options, understand defaults, or know which environment variables to set. The `AGENT_GATEWAY_` prefix and `__` nesting delimiter are undocumented.

**Files to change:**
- Part of item #6 (docs site), specifically `docs/guides/configuration.md` and `docs/api-reference/configuration.md`

**Plan:**
1. Generate a configuration reference from the Pydantic models:
   - List every config key, its type, default value, and description
   - Show the corresponding environment variable name
   - Group by section (server, model, auth, persistence, queue, etc.)
2. Provide example `gateway.yaml` files for common scenarios:
   - Local development (SQLite, no auth, console telemetry)
   - Production (PostgreSQL, OAuth2, OTLP telemetry, Redis queue)
   - Minimal (just agents, no extras)
3. Document the env var resolution: prefix `AGENT_GATEWAY_`, nesting with `__`, `${VAR}` syntax in YAML

---

### 13. API Route Unit Tests

**Problem:** API routes (`src/agent_gateway/api/routes/`) have no dedicated unit tests. They're tested indirectly through integration tests, but error paths, edge cases, and response formatting are not covered.

**Files to change:**
- `tests/test_api/` — New test directory with files for each route module

**Plan:**
1. Create `tests/test_api/` directory mirroring routes:
   - `test_invoke.py` — Test sync/async dispatch, input validation, timeout handling, streaming flag
   - `test_chat.py` — Test session creation, message validation, streaming response
   - `test_executions.py` — Test pagination, filtering, 404 for missing executions
   - `test_introspection.py` — Test agent/skill/tool listing
   - `test_schedules.py` — Test CRUD operations, pause/resume/trigger
   - `test_health.py` — Test health check response
   - `test_errors.py` — Test all error response formatting and status codes
2. Use `httpx.AsyncClient` with `TestClient` pattern
3. Mock `Gateway` internals to test route logic in isolation
4. Verify proper HTTP status codes, response schemas, and error payloads
5. Target: all routes have tests for happy path + at least 2 error paths

---

### 14. PyPI Publish Workflow

**Problem:** CI pipeline tags versions but has no step to build and upload to PyPI. The library cannot be installed via `pip install agent-gateway`.

**Files to change:**
- `.github/workflows/publish.yml` — New workflow
- `pyproject.toml` — Verify build metadata

**Plan:**
1. Create `.github/workflows/publish.yml` triggered on git tag push (`v*`)
2. Steps:
   - Checkout code
   - Set up Python + uv
   - Inject version from tag
   - Build with `uv build`
   - Publish to PyPI with `twine upload` or `uv publish` using `PYPI_TOKEN` secret
3. Add a manual trigger option for publishing pre-releases
4. Test with TestPyPI first before real publish
5. Add PyPI badge to README once first version is published

---

### 15. Package Metadata Completeness

**Problem:** Missing keywords, incomplete classifiers, no author email, no maintainers field. These affect discoverability on PyPI and user trust.

**Files to change:**
- `pyproject.toml`

**Plan:**
1. Add `keywords`:
   ```toml
   keywords = ["ai", "agents", "fastapi", "llm", "chatbot", "api", "gateway", "automation"]
   ```
2. Add missing classifiers:
   ```toml
   "Topic :: Scientific/Engineering :: Artificial Intelligence",
   "Framework :: AsyncIO",
   "Framework :: FastAPI",
   "License :: OSI Approved :: MIT License",
   ```
3. Add author email and maintainers field
4. Add `project.urls` for Documentation link (once docs site exists)
5. Verify with `uv build` and inspect wheel metadata

---

### 16. Dashboard Filtering & Real-Time Updates

**Problem:** Dashboard execution list only filters by agent_id and status. No date range filter, no cost filter, no search. Execution list is static — no live updates for running executions. Conversations are not shown as grouped entities.

**Files to change:**
- `src/agent_gateway/dashboard/router.py`
- `src/agent_gateway/dashboard/templates/executions.html`
- `src/agent_gateway/dashboard/models.py`
- `src/agent_gateway/persistence/backends/sql/repository.py`

**Plan:**
1. Add query parameters to execution listing: `date_from`, `date_to`, `min_cost`, `max_cost`
2. Add repository methods supporting these filters
3. Add HTMX polling on the executions page to refresh running executions (every 5s)
4. Add a "Conversations" view grouping executions by `session_id` with aggregated stats
5. Add execution detail link from conversation view
6. Consider adding full-text search on message/result content (PostgreSQL `ILIKE` or `tsvector`)

---

### 17. Distributed Scheduler Locking

**Problem:** If multiple gateway instances are running (horizontal scaling), each instance will fire the same scheduled job. No distributed lock prevents duplicate execution.

**Files to change:**
- `src/agent_gateway/scheduler/engine.py`
- `src/agent_gateway/config.py`

**Plan:**
1. Add optional distributed lock backend (Redis or PostgreSQL advisory lock)
2. Before firing a scheduled job, acquire a named lock (`schedule:{schedule_id}:{fire_time}`)
3. If lock acquisition fails, skip the fire (another instance is handling it)
4. Release lock after job completes or times out
5. Make locking opt-in via config: `scheduler.distributed_lock: true`
6. When queue backend is Redis, reuse the Redis connection for locking
7. Document multi-instance deployment requirements

---

### 18. CLI Output Formats

**Problem:** CLI commands like `agents`, `skills`, `schedules` only output formatted tables. No `--json` or `--csv` flag for automation, scripting, or CI pipelines.

**Files to change:**
- `src/agent_gateway/cli/list_cmd.py`
- `src/agent_gateway/cli/invoke.py`

**Plan:**
1. Add `--format` option to list commands: `table` (default), `json`, `csv`
2. Add `--format json` to `invoke` command for machine-readable output
3. Use `typer.Option` with enum for format selection
4. JSON output should match API response schemas for consistency
5. Add tests for each output format

---

### 19. Streaming Engine Tests

**Problem:** `src/agent_gateway/engine/streaming.py` has no dedicated test file. Streaming is a core feature (SSE for chat) and should be tested for token emission, tool call events, error events, and session locking.

**Files to change:**
- `tests/test_engine/test_streaming.py` — New test file

**Plan:**
1. Create test file with tests for:
   - Token event emission during streaming
   - Tool call and tool result events
   - Usage event at completion
   - Error event on LLM failure
   - Session lock acquisition and release
   - Cancellation during streaming
   - Concurrent execution semaphore enforcement
2. Use `MockLLMClient` from existing conftest with streaming response support
3. Verify SSE event format (`event: type\ndata: json\n\n`)

---

### 20. Dashboard Test Coverage

**Problem:** Dashboard module has only 1 test file (OAuth2). Router, auth, and models are untested. The dashboard is a key feature for businesses evaluating the library.

**Files to change:**
- `tests/test_dashboard/` — New test files

**Plan:**
1. Add `test_auth.py` — Test password login, session cookies, logout, protected routes
2. Add `test_router.py` — Test all dashboard pages render, HTMX partial responses, error states
3. Add `test_models.py` — Test view model formatting (cost formatting, relative time, status badges)
4. Use `httpx.AsyncClient` with test Gateway instance
5. Mock persistence repositories for deterministic test data

---

### 21. Notification Delivery Confirmation

**Problem:** Notifications are fire-and-forget. Failed webhook deliveries are silently dropped with no audit trail or retry visibility. Businesses need to know if critical notifications (e.g., "agent failed on production task") were delivered.

**Files to change:**
- `src/agent_gateway/notifications/models.py` — Add delivery status tracking
- `src/agent_gateway/notifications/engine.py` — Track delivery results
- `src/agent_gateway/persistence/domain.py` — Add `notification_log` table
- `src/agent_gateway/api/routes/` — Optional notifications status endpoint

**Plan:**
1. Add `NotificationDelivery` domain model (id, event_type, backend, target, status, attempts, last_error, timestamps)
2. Add `notification_log` table to persistence layer
3. Update `NotificationEngine` to persist delivery results after each attempt
4. Add `GET /v1/notifications?status=failed` endpoint for visibility
5. Add dashboard page showing recent notification deliveries
6. Consider adding a webhook retry button in the dashboard

---

### 22. Session Persistence

**Problem:** `SessionStore` is in-memory only. Chat sessions are lost on server restart. For businesses running production chat agents, this means users lose their conversation context on every deployment.

**Files to change:**
- `src/agent_gateway/chat/session.py` — Add persistence hooks
- `src/agent_gateway/persistence/protocols.py` — Add `SessionRepository` protocol
- `src/agent_gateway/persistence/backends/sql/repository.py` — Implement SQL session storage

**Plan:**
1. Add `SessionRepository` protocol with `save()`, `load()`, `delete()`, `list()` methods
2. Implement SQL-backed session storage (serialize messages as JSON)
3. Update `SessionStore` to optionally back sessions with persistence:
   - On session creation/update → async persist
   - On session access (cache miss) → load from DB
   - Keep in-memory cache as hot layer, DB as cold storage
4. Add config option: `chat.persist_sessions: true` (default false for backward compat)
5. Add session restore on startup
6. Add tests for persistence round-trip

---

### 23. Missing Database Indexes

**Problem:** Several common query patterns lack indexes: `executions.created_at` (used in `cost_by_day`, `executions_by_day`), `executions.status` (used in filtering), `conversations.created_at` (used in listing).

**Files to change:**
- `src/agent_gateway/persistence/backends/sql/base.py` — Add indexes to table definitions

**Plan:**
1. Add indexes:
   - `ix_executions_created_at` on `executions.created_at`
   - `ix_executions_status` on `executions.status`
   - `ix_conversations_created_at` on `conversations.created_at`
   - `ix_audit_log_created_at` on `audit_log.created_at`
2. Include these as part of the initial Alembic migration (item #2)
3. For existing databases, the Alembic migration will add them

---

## Additional Items Noted (Not Blocking Publish)

These are quality improvements that can be addressed post-launch:

- **CONTRIBUTING.md** — Add contributor guide (linting, testing, PR process)
- **CHANGELOG.md** — Start maintaining a changelog (can auto-generate from conventional commits)
- **Hook return values** — Hooks are fire-and-forget; consider allowing pre-hooks to cancel operations
- **Per-agent guardrails** — Currently global; consider per-agent `max_iterations`, `timeout_ms` overrides in AGENT.md frontmatter
- **Webhook signature standard** — Current custom format; consider aligning with Standard Webhooks spec
- **Telemetry sampling** — No sampling strategy; could be expensive at high volume
- **Priority queues** — All jobs are FIFO; no priority support
- **APScheduler upgrade** — v3.x is old; monitor v4 for stability before upgrading
- **Dashboard accessibility** — ARIA labels, keyboard navigation, color contrast verification
- **Dashboard data export** — CSV/JSON export of analytics data

---

## Execution Order Recommendation

```
Phase 1 — Packaging (do first, unblocks everything):
  #4  Version management
  #15 Package metadata
  #14 PyPI publish workflow
  #3  README

Phase 2 — Data integrity (required for production):
  #1  Conversation tracing
  #2  Database migrations
  #23 Missing indexes

Phase 3 — Core features (key differentiators):
  #7  Per-user agent configuration
  #8  Agent-to-agent communication

Phase 4 — Security (required for production APIs):
  #5  CORS middleware
  #10 Security headers
  #9  Rate limiting

Phase 5 — Documentation (required for adoption):
  #6  User-facing docs site
  #12 Configuration reference
  #11 OpenAPI endpoint docs

Phase 6 — Testing:
  #13 API route unit tests
  #19 Streaming tests
  #20 Dashboard tests

Phase 7 — Post-launch improvements:
  #16-#22 (remaining P2 items)
```
