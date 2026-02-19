# Agent Gateway — Test Project

A working example that demonstrates the core features of `agent-gateway`:
API key authentication, PostgreSQL persistence, RabbitMQ queue for async
execution, and multiple agent types (sync and async).

## What's Included

```
workspace/
├── gateway.yaml                    # Server and model configuration
├── agents/
│   ├── AGENTS.md                   # Shared system prompt for all agents
│   ├── assistant/                  # General-purpose assistant agent (sync)
│   │   ├── AGENT.md                # Agent prompt + tool/skill bindings
│   │   └── SOUL.md                 # Personality traits
│   ├── data-processor/             # Long-running data processor (async)
│   │   └── AGENT.md                # execution_mode: async
│   ├── scheduled-reporter/         # Agent with a cron schedule (disabled)
│   │   └── AGENT.md
│   └── travel-planner/             # Travel planning agent (sync)
│       └── AGENT.md
├── skills/
│   └── math-workflow/
│       └── SKILL.md                # Multi-step arithmetic skill
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

# Start infrastructure (PostgreSQL + RabbitMQ):
docker compose -f examples/test-project/docker-compose.yml up -d

# Wait for services to be healthy:
docker compose -f examples/test-project/docker-compose.yml ps
```

## Run

```bash
# From the repository root:
make dev

# Or directly:
uv run --directory examples/test-project python app.py
```

The server starts at `http://localhost:8000`. OpenAPI docs are at `http://localhost:8000/docs`.

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
