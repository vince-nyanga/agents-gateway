# Quickstart

This guide walks you from zero to a running agent service in under five minutes.

## 1. Scaffold a Project

Use the CLI to generate a new project:

```bash
agents-gateway init myproject
cd myproject
```

This creates a minimal project with a default workspace layout and an `app.py` entry point.

## 2. Start the Server

```bash
agents-gateway serve
```

The server starts on `http://localhost:8000`. Interactive API documentation is available at `http://localhost:8000/docs`.

## 3. Define an Agent

Agents are defined as Markdown files inside the workspace. Create a new agent by adding an `AGENT.md` file:

```
workspace/agents/assistant/AGENT.md
```

```markdown
---
description: A helpful general-purpose assistant.
skills: []
memory: false
---

You are a helpful assistant. Answer questions clearly and concisely.
When you do not know the answer to something, say so honestly.
```

The YAML frontmatter configures the agent. The Markdown body is the agent's system prompt.

Restart the server (or rely on hot-reload if enabled) and the agent will be available at `/v1/agents/assistant`.

## 4. Invoke the Agent

Send a one-shot request to the agent:

```bash
curl -X POST http://localhost:8000/v1/agents/assistant/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

The response includes the agent's reply:

```json
{
  "agent_id": "assistant",
  "message": "Hello! How can I help you today?",
  "metadata": {}
}
```

## 5. Add a Tool

Tools give agents capabilities beyond text generation. Register a tool in `app.py` using the `@gw.tool` decorator:

```python
from agent_gateway import Gateway

gw = Gateway()

@gw.tool(name="get_weather", description="Get the current weather for a city.")
def get_weather(city: str) -> str:
    # Replace with a real weather API call.
    return f"It is sunny and 22°C in {city}."

if __name__ == "__main__":
    gw.run()
```

Reference the tool by name in your agent's frontmatter:

```markdown
---
description: A helpful assistant that can check the weather.
skills: []
tools:
  - get_weather
memory: false
---

You are a helpful assistant. Use the get_weather tool whenever a user asks about weather.
```

## 6. Use the Chat Endpoint

For multi-turn conversations, use the chat endpoint instead of invoke:

```bash
curl -X POST http://localhost:8000/v1/agents/assistant/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather in London?", "session_id": "session-abc"}'
```

Pass the same `session_id` across requests to maintain conversation history.

## Mounting into an Existing App

If you already have a FastAPI application, you can mount the gateway as a sub-app instead of running it standalone:

```python
from fastapi import FastAPI
from agent_gateway import Gateway

app = FastAPI(title="My Application")

gw = Gateway(workspace="./workspace")
gw.mount_to(app, path="/ai")

# Gateway API at /ai/v1/..., dashboard at /ai/dashboard/
```

All features (dashboard, auth, scheduling, etc.) work identically when mounted. See the [Sub-App Mounting guide](../guides/mounting.md) for details.

## Next Steps

- [Project Structure](./project-structure.md) — understand the workspace layout in detail
- Agents guide — configure skills, memory, and behavioral guardrails
- Tools guide — write and register tools
- Authentication guide — add OAuth2 or API key auth
- [Sub-App Mounting](../guides/mounting.md) — integrate into an existing FastAPI app
