# Agent Gateway — Test Project

A working example that demonstrates the core features of `agent-gateway`:
API key authentication, PostgreSQL persistence, RabbitMQ queue for async
execution, pluggable notification backends (Slack/Webhook), Pydantic
structured output schemas, and multiple agent types (sync and async).

## What's Included

```
workspace/
├── gateway.yaml                    # Server and model configuration
├── agents/
│   ├── AGENTS.md                   # Shared system prompt for all agents
│   ├── assistant/                  # General-purpose assistant agent (sync)
│   │   ├── AGENT.md                # Agent prompt + tool/skill bindings
│   │   └── BEHAVIOR.md              # Behavioral guardrails
│   ├── data-analyst/               # BigQuery data analyst (MCP + public datasets)
│   │   └── AGENT.md
│   ├── data-processor/             # Long-running data processor (async + notifications)
│   │   └── AGENT.md                # execution_mode: async, notifications on all events
│   ├── scheduled-reporter/         # Agent with cron schedules + per-schedule instructions
│   │   └── AGENT.md                # Two schedules with different instructions
│   └── travel-planner/             # Travel planning agent (sync + notifications)
│       └── AGENT.md                # Notifications on complete/error
├── skills/
│   ├── math-workflow/
│   │   └── SKILL.md                # Workflow skill with automated steps
│   ├── general-tools/
│   │   └── SKILL.md                # General-purpose tool skill
│   ├── data-processing/
│   │   └── SKILL.md                # Data processing tool skill
│   └── travel-planning/
│       └── SKILL.md                # Travel planning tool skill
└── tools/
    ├── http-example/
    │   ├── TOOL.md                 # Tool definition with parameters
    │   └── handler.py              # Python handler for HTTP requests
    ├── search-activities/
    │   └── TOOL.md
    └── search-hotels/
        └── TOOL.md
```

**Code tools** (`echo`, `add_numbers`, `process-data`, `search-flights`, `get-weather`)
are registered in `app.py` using `@gw.tool()`.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [Docker](https://docs.docker.com/get-docker/) (for PostgreSQL and RabbitMQ)
- A Gemini API key (the default model is `gemini/gemini-2.0-flash`)

## Setup

```bash
# From the repository root:
cp examples/test-project/.env.example examples/test-project/.env

# Edit .env and add your Gemini API key:
# GEMINI_API_KEY=your-key-here

# Optional: add Slack/Webhook notification credentials:
# SLACK_BOT_TOKEN=xoxb-...
# WEBHOOK_URL=https://your-endpoint.example.com/webhook

# Start infrastructure (PostgreSQL + RabbitMQ):
docker compose -f examples/test-project/docker-compose.yml up -d

# Wait for services to be healthy:
docker compose -f examples/test-project/docker-compose.yml ps
```

## Database Migrations

Agent Gateway uses Alembic for database migrations. On first startup, migrations
run automatically. When upgrading, apply new migrations:

```bash
# Apply all pending migrations
agents-gateway db upgrade --workspace examples/test-project/workspace

# Check current migration version
agents-gateway db current --workspace examples/test-project/workspace

# View migration history
agents-gateway db history --workspace examples/test-project/workspace

# Roll back one migration
agents-gateway db downgrade --workspace examples/test-project/workspace
```

## Run

The test project can run in two modes: **standalone** (Gateway is the app) or **mounted** (Gateway is a sub-app inside an existing FastAPI app).

### Standalone mode

```bash
# From the repository root:
make dev

# Or directly:
uv run --directory examples/test-project python app.py
```

The server starts at `http://localhost:8000`. OpenAPI docs are at `http://localhost:8000/docs`.
Dashboard at `http://localhost:8000/dashboard/`.

### Mounted mode (sub-app)

```bash
# From the repository root:
make dev-mounted

# Or directly:
uv run --directory examples/test-project python app_mounted.py
```

The Gateway is mounted at `/ai` inside a parent FastAPI app. All features work identically:

| Standalone | Mounted |
|---|---|
| `http://localhost:8000/v1/health` | `http://localhost:8000/ai/v1/health` |
| `http://localhost:8000/dashboard/` | `http://localhost:8000/ai/dashboard/` |
| `http://localhost:8000/docs` | `http://localhost:8000/ai/docs` |

The parent app has its own routes at `/` and `/api/status`.

### Server Configurations

The test project supports several configurations controlled by environment variables.
Both `app.py` and `app_mounted.py` support these. Combine them as needed.

#### Default (password auth + static API key)

```bash
make dev          # standalone
make dev-mounted  # mounted
```

Dashboard login: `admin`/`adminpass` (full access) or `user`/`userpass` (limited access).
API key: `dev-api-key-change-me` via `Authorization: Bearer` header.

#### Keycloak OAuth2 for dashboard SSO

```bash
KEYCLOAK_DASHBOARD=1 make dev           # standalone
KEYCLOAK_DASHBOARD=1 make dev-mounted   # mounted
```

The dashboard login page shows a "Sign in with Keycloak" SSO button.
Admin credentials (`admin`/`adminpass`) are available as a collapsible fallback
beneath the SSO button for break-glass access.

Requires a running Keycloak instance (see `KEYCLOAK_URL`, `KEYCLOAK_REALM` env vars).

#### Keycloak OAuth2 for API auth

```bash
KEYCLOAK_API=1 make dev           # standalone
KEYCLOAK_API=1 make dev-mounted   # mounted
```

Replaces static API keys with OAuth2 JWT validation on all `/v1/` endpoints.
Swagger UI shows a login button for obtaining tokens.

#### Both Keycloak OAuth2 (dashboard + API)

```bash
KEYCLOAK_DASHBOARD=1 KEYCLOAK_API=1 make dev           # standalone
KEYCLOAK_DASHBOARD=1 KEYCLOAK_API=1 make dev-mounted   # mounted
```

#### Environment variable reference

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_DASHBOARD` | _(unset)_ | Set to `1` to use Keycloak SSO for the dashboard |
| `KEYCLOAK_API` | _(unset)_ | Set to `1` to use Keycloak OAuth2 for API auth |
| `KEYCLOAK_URL` | `http://localhost:8080` | Keycloak server URL |
| `KEYCLOAK_REALM` | `agent-gateway` | Keycloak realm name |
| `KEYCLOAK_DASHBOARD_CLIENT_ID` | `agw-dashboard` | OAuth2 client ID for dashboard |
| `KEYCLOAK_DASHBOARD_CLIENT_SECRET` | `agw-dashboard-secret` | OAuth2 client secret for dashboard |
| `KEYCLOAK_API_CLIENT_ID` | `agw-api` | OAuth2 client ID for API |
| `KEYCLOAK_API_CLIENT_SECRET` | `agw-api-secret` | OAuth2 client secret for API |
| `DASHBOARD_ADMIN_PASSWORD` | `adminpass` | Admin password for dashboard |
| `DASHBOARD_PASSWORD` | `userpass` | Regular user password for dashboard |
| `AGENT_GATEWAY_API_KEY` | `dev-api-key-change-me` | Static API key (when not using OAuth2) |
| `GEMINI_API_KEY` | _(required)_ | API key for the Gemini LLM |
| `POSTGRES_URL` | `postgresql+asyncpg://...localhost:54320/...` | PostgreSQL connection string |
| `RABBITMQ_URL` | `amqp://...localhost:56720/` | RabbitMQ connection string |
| `SLACK_BOT_TOKEN` | _(unset)_ | Slack bot token for notifications |
| `SLACK_DEFAULT_CHANNEL` | `#agent-alerts` | Default Slack channel |
| `WEBHOOK_URL` | _(unset)_ | Webhook URL for notifications |

## Data Analyst Agent (BigQuery MCP)

The **Data Analyst** agent queries Google BigQuery public datasets via the MCP protocol. It requires a Google Cloud project with a service account.

### Setup

#### 1. Install the Google Cloud CLI

```bash
brew install google-cloud-sdk
```

#### 2. Login and set your project

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

#### 3. Enable the BigQuery API

```bash
gcloud services enable bigquery.googleapis.com
```

#### 4. Create a service account

```bash
gcloud iam service-accounts create bigquery-agent \
  --display-name="BigQuery Agent"
```

#### 5. Grant BigQuery access

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:bigquery-agent@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.user"
```

#### 6. Download the key file

```bash
gcloud iam service-accounts keys create examples/test-project/creds/bigquery-sa-key.json \
  --iam-account=bigquery-agent@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

> **Important:** Never commit this file. The `creds/` directory is gitignored.

#### 7. Add environment variables

Add the following to `examples/test-project/.env`:

```bash
BIGQUERY_PROJECT=YOUR_PROJECT_ID
AGENT_GATEWAY_SECRET_KEY=any-string-at-least-32-characters-long
```

#### 8. Start the server

```bash
make dev
```

### Usage

Open the dashboard at `http://localhost:8000/dashboard` (or `http://localhost:8000/ai/dashboard` in mounted mode), log in as `admin`/`adminpass`, and select the **Data Analyst** agent. Example questions:

- "What were the top 10 most popular baby names in 2020?"
- "Which names had the biggest rise in popularity from the 1950s to the 2010s?"
- "What programming languages on GitHub share names with American babies?"

The agent has access to these public datasets:

| Dataset | Description |
|---------|-------------|
| `bigquery-public-data.usa_names.usa_1910_current` | US baby names by year, state, gender |
| `bigquery-public-data.samples.shakespeare` | Complete works of Shakespeare |
| `bigquery-public-data.github_repos.languages` | GitHub repository languages |
| `bigquery-public-data.stackoverflow.posts_questions` | Stack Overflow questions |

### Cost

- First 1 TB/month of queries is free
- Public dataset storage is free
- You only pay for data scanned by your queries

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BIGQUERY_PROJECT` | _(unset)_ | GCP project ID (enables BigQuery MCP) |
| `BIGQUERY_LOCATION` | `us` | BigQuery processing location |
| `GOOGLE_APPLICATION_CREDENTIALS` | `creds/bigquery-sa-key.json` | Path to service account key file |
| `AGENT_GATEWAY_SECRET_KEY` | _(required for MCP)_ | Encryption key for MCP server credentials |

## CLI Output Formats

The `agents`, `skills`, and `schedules` commands support `--format` (`-f`) to
output as `table` (default), `json`, or `csv`:

```bash
# JSON output for scripting
agents-gateway agents -w workspace --format json

# CSV for spreadsheets
agents-gateway skills -w workspace --format csv

# Table (default)
agents-gateway schedules -w workspace --format table
```

The `invoke` command supports `--format json` (or the legacy `--json` flag):

```bash
agents-gateway invoke assistant "Hello" -w workspace --format json
```

## Try It

All `/v1/` endpoints require an API key via the `Authorization` header.
The default dev key is `dev-api-key-change-me` (set via `AGENT_GATEWAY_API_KEY` in `.env`).

```bash
# Health check (no auth required)
curl http://localhost:8000/v1/health

# List agents
curl http://localhost:8000/v1/agents \
  -H "Authorization: Bearer dev-api-key-change-me"

# Invoke the assistant (synchronous)
curl -X POST http://localhost:8000/v1/agents/assistant/invoke \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-api-key-change-me" \
  -d '{"message": "What is 2 + 3?"}'

# Start a chat session
curl -X POST http://localhost:8000/v1/agents/assistant/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-api-key-change-me" \
  -d '{"message": "Hello!"}'

# Continue the chat (use the session_id from the response above)
curl -X POST http://localhost:8000/v1/agents/assistant/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-api-key-change-me" \
  -d '{"message": "What can you do?", "session_id": "sess_..."}'
```

> **Session persistence:** When PostgreSQL persistence is enabled, chat sessions
> survive server restarts. If a session is not in the in-memory cache (e.g., after
> a restart), it is automatically rehydrated from the `conversations` table. Session
> metadata and tool-call messages are **not** restored on rehydration.


### Async Execution

The `data-processor` agent runs asynchronously via RabbitMQ. Invoking it
returns `202 Accepted` immediately with a `poll_url` to check progress.

```bash
# Invoke the async data processor (returns 202 immediately)
curl -X POST http://localhost:8000/v1/agents/data-processor/invoke \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-api-key-change-me" \
  -d '{"message": "Analyze last month sales data"}'

# Response:
# {
#   "execution_id": "abc-123",
#   "agent_id": "data-processor",
#   "status": "queued",
#   "poll_url": "/v1/executions/abc-123"
# }

# Poll for results (use the execution_id from the 202 response)
curl http://localhost:8000/v1/executions/abc-123 \
  -H "Authorization: Bearer dev-api-key-change-me"

# Cancel a running execution
curl -X POST http://localhost:8000/v1/executions/abc-123/cancel \
  -H "Authorization: Bearer dev-api-key-change-me"
```

### Structured Output (Pydantic Models)

The gateway accepts Pydantic models as output schemas. The model is
automatically converted to JSON Schema for the LLM prompt, and the
response is parsed back into a validated model instance.

```python
from pydantic import BaseModel
from agent_gateway.engine.models import ExecutionOptions

class MathResult(BaseModel):
    answer: float
    explanation: str

result = await gw.invoke(
    "assistant", "What is 12 * 15?",
    options=ExecutionOptions(output_schema=MathResult),
)
assert isinstance(result.output, MathResult)
print(result.output.answer)  # 180.0
```

Two demo endpoints are included in `app.py`:

```bash
# Structured math output
curl http://localhost:8000/api/demo/structured-output

# Structured travel plan
curl http://localhost:8000/api/demo/travel-plan
```

Raw `dict` schemas continue to work identically — passing a `dict` to
`output_schema` behaves exactly as before.

### Notifications

Agents can send notifications on completion, error, or timeout. Configure
backends in `app.py` via the fluent API:

```python
# Slack (requires SLACK_BOT_TOKEN env var)
gw.use_slack_notifications(bot_token="xoxb-...", default_channel="#agent-alerts")

# Webhooks (HMAC-signed POST requests)
gw.use_webhook_notifications(url="https://...", name="default", secret="s3cret")
```

Then declare per-agent notification rules in `AGENT.md` frontmatter:

```yaml
---
notifications:
  on_complete:
    - channel: slack
      target: "#travel-plans"
  on_error:
    - channel: webhook
      target: default
---
```

In this project, `travel-planner` and `data-processor` have notification
configs. Set `SLACK_BOT_TOKEN` and/or `WEBHOOK_URL` in `.env` to activate
them.

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/v1/health` | No | Gateway health check |
| GET | `/v1/agents` | Yes | List all agents |
| GET | `/v1/agents/{id}` | Yes | Get agent details |
| POST | `/v1/agents/{id}/invoke` | Yes | Invoke an agent (single-turn) |
| POST | `/v1/agents/{id}/chat` | Yes | Chat with an agent (multi-turn) |
| GET | `/v1/executions/{id}` | Yes | Get execution status/result |
| POST | `/v1/executions/{id}/cancel` | Yes | Cancel a running execution |
| GET | `/v1/skills` | Yes | List all skills |
| GET | `/v1/tools` | Yes | List all tools |
| GET | `/v1/sessions` | Yes | List active chat sessions |
| GET | `/v1/sessions/{id}` | Yes | Get session details |
| DELETE | `/v1/sessions/{id}` | Yes | Delete a session |
| GET | `/api/health` | No | Custom route (defined in app.py) |
| GET | `/api/demo/structured-output` | No | Pydantic output schema demo (math) |
| GET | `/api/demo/travel-plan` | No | Pydantic output schema demo (travel) |

## Infrastructure

| Service | Host Port |
|---------|-----------|
| PostgreSQL | 54320 |
| RabbitMQ (AMQP) | 56720 |

## Teardown

```bash
# Stop services (data persists in Docker volume):
docker compose -f examples/test-project/docker-compose.yml down

# Stop services and remove all data:
docker compose -f examples/test-project/docker-compose.yml down -v
```
