# Agent Gateway — Test Project

A working example that demonstrates the core features of `agent-gateway`.

## What's Included

```
workspace/
├── gateway.yaml                    # Server and model configuration
├── agents/
│   ├── AGENTS.md                   # Shared system prompt for all agents
│   ├── assistant/                  # General-purpose assistant agent
│   │   ├── AGENT.md                # Agent prompt
│   │   ├── CONFIG.md               # Skills, tools, and model config
│   │   └── SOUL.md                 # Personality traits
│   └── scheduled-reporter/         # Agent with a cron schedule (disabled)
│       ├── AGENT.md
│       └── CONFIG.md
├── skills/
│   └── math-workflow/
│       └── SKILL.md                # Multi-step arithmetic skill
└── tools/
    └── http-example/
        ├── TOOL.md                 # Tool definition with parameters
        └── handler.py              # Python handler for HTTP requests
```

**Code tools** (`echo`, `add_numbers`) are registered in `app.py` using `@gw.tool()`.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A Gemini API key (the default model is `gemini/gemini-2.0-flash`)

## Setup

```bash
# From the repository root:
cp examples/test-project/.env.example examples/test-project/.env

# Edit .env and add your Gemini API key:
# GEMINI_API_KEY=your-key-here
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

```bash
# Health check
curl http://localhost:8000/v1/health

# List agents
curl http://localhost:8000/v1/agents

# Invoke the assistant
curl -X POST http://localhost:8000/v1/agents/assistant/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2 + 3?"}'

# Start a chat session
curl -X POST http://localhost:8000/v1/agents/assistant/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'

# Continue the chat (use the session_id from the response above)
curl -X POST http://localhost:8000/v1/agents/assistant/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What can you do?", "session_id": "sess_..."}'
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/health` | Gateway health check |
| GET | `/v1/agents` | List all agents |
| GET | `/v1/agents/{id}` | Get agent details |
| POST | `/v1/agents/{id}/invoke` | Invoke an agent (single-turn) |
| POST | `/v1/agents/{id}/chat` | Chat with an agent (multi-turn) |
| GET | `/v1/skills` | List all skills |
| GET | `/v1/tools` | List all tools |
| GET | `/v1/sessions` | List active chat sessions |
| GET | `/v1/sessions/{id}` | Get session details |
| DELETE | `/v1/sessions/{id}` | Delete a session |
| GET | `/api/health` | Custom route (defined in app.py) |
