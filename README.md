<p align="center">
  <img src="https://raw.githubusercontent.com/vince-nyanga/agents-gateway/main/docs/assets/icon.png" alt="Agent Gateway" width="120">
</p>

# Agent Gateway

[![PyPI version](https://img.shields.io/pypi/v/agents-gateway)](https://pypi.org/project/agents-gateway/)
[![Python](https://img.shields.io/pypi/pyversions/agents-gateway)](https://pypi.org/project/agents-gateway/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/vince-nyanga/agents-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/vince-nyanga/agents-gateway/actions/workflows/ci.yml)

A FastAPI extension for building API-first AI agent services. Define agents, tools, and skills as markdown files, then serve them as a production-ready API with authentication, persistence, scheduling, notifications, and more.

## Quick Start

```bash
pip install agents-gateway[all]

# Scaffold a new project
agents-gateway init myproject
cd myproject

# Start the server
agents-gateway serve
```

Your agent API is now running at `http://localhost:8000` with interactive docs at `/docs`.

## Define an Agent

Create a markdown file at `workspace/agents/assistant/AGENT.md`:

```markdown
---
description: A helpful assistant that answers questions
skills:
  - general-tools
memory:
  enabled: true
---

You are a helpful assistant. Answer questions clearly and concisely.
```

That's it — the agent is now available via the API.

## Add a Tool

### File-based tool

Create `workspace/tools/http-example/TOOL.md`:

```markdown
---
name: http-example
description: Make an HTTP GET request and return the response
parameters:
  url:
    type: string
    description: The URL to fetch
    required: true
---
```

Add a handler in `workspace/tools/http-example/handler.py`:

```python
import httpx

async def handler(url: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return resp.text
```

### Code-based tool

Register tools directly in Python:

```python
from agent_gateway import Gateway

gw = Gateway(workspace="./workspace")

@gw.tool(agent="assistant")
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b
```

## Use the API

```bash
# Invoke an agent (single-turn)
curl -X POST http://localhost:8000/v1/agents/assistant/invoke \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"message": "What is 2 + 3?"}'

# Chat with an agent (multi-turn)
curl -X POST http://localhost:8000/v1/agents/assistant/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"message": "Hello!"}'
```

## Features

- **Markdown-defined agents** — Define agents, tools, and skills as markdown files with YAML frontmatter
- **Multi-LLM support** — Use any model supported by [LiteLLM](https://docs.litellm.ai/) (OpenAI, Gemini, Anthropic, Ollama, etc.)
- **Built-in authentication** — API key and OAuth2/JWT auth out of the box
- **Persistence** — SQLite or PostgreSQL storage for conversations, executions, and audit logs
- **Dashboard** — Built-in web dashboard for monitoring agents, executions, and conversations
- **Scheduling** — Cron-based agent scheduling via APScheduler
- **Notifications** — Slack and webhook notification backends with per-agent rules
- **Async execution** — Queue-based async processing with Redis or RabbitMQ
- **Telemetry** — OpenTelemetry instrumentation with console or OTLP export
- **Structured output** — Pydantic model or JSON Schema output validation
- **Agent memory** — Automatic memory extraction and recall across conversations
- **Streaming** — Server-sent events (SSE) for real-time chat responses
- **Input/output schemas** — JSON Schema validation for agent inputs and outputs
- **CLI** — Project scaffolding, agent listing, and dev server via `agents-gateway` CLI
- **Lifecycle hooks** — `before_invoke`, `after_invoke`, `on_error` hooks for custom logic
- **Sub-app mounting** — Mount into an existing FastAPI app with `gw.mount_to(app, path="/ai")` — full feature parity

## Sub-App Mounting

Mount the gateway into an existing FastAPI app with full feature parity — dashboard, auth, OAuth2, static assets, and all background subsystems work identically:

```python
from fastapi import FastAPI
from agent_gateway import Gateway

app = FastAPI(title="My App")
gw = Gateway(workspace="./workspace")

gw.use_api_keys([{"name": "dev", "key": "secret", "scopes": ["*"]}])
gw.use_dashboard(auth_username="user", auth_password="pass",
                 admin_username="admin", admin_password="admin")

gw.mount_to(app, path="/ai")

# Your routes at /
# Gateway API at /ai/v1/...
# Dashboard at /ai/dashboard/
```

See the [mounting guide](https://vince-nyanga.github.io/agents-gateway/guides/mounting/) for details.

## Configuration

Configure your gateway with `workspace/gateway.yaml`:

```yaml
server:
  port: 8000

model:
  default: "gemini/gemini-2.0-flash"
  temperature: 0.1

memory:
  enabled: true
```

Or configure programmatically:

```python
from agent_gateway import Gateway

gw = Gateway(
    workspace="./workspace",
    title="My Agent Service",
)

# Fluent API for backends
gw.use_api_key_auth(api_key="your-key")
gw.use_sqlite("sqlite+aiosqlite:///data.db")
gw.use_slack_notifications(bot_token="xoxb-...", default_channel="#alerts")
```

## Installation Extras

Install only what you need:

```bash
pip install agents-gateway[sqlite]       # SQLite persistence
pip install agents-gateway[postgres]     # PostgreSQL persistence
pip install agents-gateway[redis]        # Redis queue backend
pip install agents-gateway[rabbitmq]     # RabbitMQ queue backend
pip install agents-gateway[oauth2]       # OAuth2/JWT authentication
pip install agents-gateway[slack]        # Slack notifications
pip install agents-gateway[dashboard]    # Web dashboard
pip install agents-gateway[otlp]        # OTLP telemetry export
pip install agents-gateway[all]          # Everything
```

## Documentation

Full documentation is available at [vince-nyanga.github.io/agents-gateway](https://vince-nyanga.github.io/agents-gateway/).

## License

MIT
