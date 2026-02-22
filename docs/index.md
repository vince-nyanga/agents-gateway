# Agents Gateway

A FastAPI extension for building API-first AI agent services.

Define agents, tools, and skills as markdown files, then serve them as a production-ready API with authentication, persistence, scheduling, notifications, and more.

## Why Agent Gateway?

Building AI agent services requires significant boilerplate: API endpoints, authentication, persistence, monitoring, scheduling, and more. Agent Gateway handles all of this so you can focus on defining your agents.

- **Markdown-first** — Define agents, tools, and skills as markdown files with YAML frontmatter. No complex framework to learn.
- **Production-ready** — Built-in auth, persistence, telemetry, rate limiting, and error handling.
- **Multi-LLM** — Use any model supported by [LiteLLM](https://docs.litellm.ai/) (OpenAI, Gemini, Anthropic, Ollama, and more).
- **Extensible** — Plug in custom auth providers, persistence backends, notification channels, and context retrievers.

## Quick Start

```bash
pip install agents-gateway[all]
agents-gateway init myproject
cd myproject
agents-gateway serve
```

Your agent API is now running at `http://localhost:8000` with interactive docs at `/docs`.

## Features

| Feature | Description |
|---------|-------------|
| [Agents](guides/agents.md) | Define agents as markdown files with YAML frontmatter |
| [Tools](guides/tools.md) | File-based or code-based tools with automatic schema inference |
| [Skills](guides/skills.md) | Composable workflows with sequential and parallel steps |
| [Authentication](guides/authentication.md) | API key and OAuth2/JWT auth out of the box |
| [Persistence](guides/persistence.md) | SQLite or PostgreSQL with Alembic migrations |
| [Dashboard](guides/dashboard.md) | Web dashboard for monitoring agents, executions, and conversations |
| [Scheduling](guides/scheduling.md) | Cron-based agent scheduling |
| [Notifications](guides/notifications.md) | Slack and webhook notifications with per-agent rules |
| [Queue](guides/queue.md) | Async execution with Redis or RabbitMQ |
| [Memory](guides/memory.md) | Automatic memory extraction and recall |
| [Telemetry](guides/telemetry.md) | OpenTelemetry instrumentation |
| [Structured Output](guides/structured-output.md) | Pydantic model or JSON Schema output validation |
| [Context Retrieval](guides/context-retrieval.md) | RAG integration via pluggable retrievers |
| [CORS](guides/cors.md) | CORS middleware for browser clients |
| [Streaming](guides/agents.md) | SSE for real-time chat responses |
| [CLI](getting-started/quickstart.md) | Project scaffolding, dev server, agent management |

## Next Steps

- [Installation](getting-started/installation.md) — Install the package and extras
- [Quick Start](getting-started/quickstart.md) — Build your first agent in 5 minutes
- [Project Structure](getting-started/project-structure.md) — Understand the workspace layout
- [Configuration](guides/configuration.md) — Full configuration reference
