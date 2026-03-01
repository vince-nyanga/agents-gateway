# Agents

Agents are the core unit of Agent Gateway. Each agent is defined by a directory under `workspace/agents/` containing an `AGENT.md` file. The file's YAML frontmatter configures the agent's behaviour and the Markdown body becomes its system prompt.

## Directory structure

```
workspace/
  agents/
    AGENTS.md          # Optional: shared system prompt injected into every agent
    BEHAVIOR.md        # Optional: shared behavioral guardrails for every agent
    <agent-id>/
      AGENT.md         # Required: system prompt + frontmatter config
      BEHAVIOR.md      # Optional: per-agent behavioral guardrails
      context/         # Optional: static Markdown files injected as context
        reference.md
        style-guide.md
```

The agent's ID is the name of its directory (e.g. `travel-planner`). Agent IDs must be unique within the workspace.

## AGENT.md structure

An `AGENT.md` file has two parts: a YAML frontmatter block (between `---` delimiters) and a Markdown body that becomes the agent's system prompt.

```markdown
---
description: "Plans multi-day travel itineraries"
display_name: "Travel Planner"
tags: [travel, planning]
version: "1.0.0"
skills:
  - travel-planning
---

# Travel Planner

You are a travel planning assistant. When you have all the travel details,
call the available tools to build a comprehensive itinerary.
```

The body must not be empty — an agent with no system prompt is skipped at load time.

## Frontmatter reference

### Metadata

| Field | Type | Description |
|---|---|---|
| `description` | string | Short description shown in the API and dashboard |
| `display_name` | string | Human-readable name (defaults to agent ID) |
| `tags` | list[string] | Arbitrary tags for grouping and filtering |
| `version` | string | Semantic version string |

### Skills

```yaml
skills:
  - travel-planning
  - general-tools
```

Agents gain access to tools exclusively through skills. Each entry is a skill ID matching a directory under `workspace/skills/`. Skills are resolved at startup; a warning is logged for any unknown skill IDs.

### Model override

Each agent can override the global model configuration from `gateway.yaml`:

```yaml
model:
  name: gpt-4o           # Model identifier (LiteLLM format)
  temperature: 0.7       # Sampling temperature
  max_tokens: 8192       # Maximum output tokens
  fallback: gpt-4o-mini  # Model to use if primary fails
```

All fields are optional. Omitted fields inherit the global defaults.

- `name` accepts any [LiteLLM model identifier](https://docs.litellm.ai/docs/providers). It is automatically registered in the LLM router at startup, so retry and cooldown policies apply.
- `fallback` designates a fallback model used when the primary fails. Must be a valid LiteLLM model identifier.
- The reserved names `"default"` and `"fallback"` must not be used as `model.name` — they are used internally by the router for the global model configuration.

### Delegation

Agents can delegate tasks to other agents using the built-in `delegate_to_agent` tool:

```yaml
delegates_to:
  - researcher
  - writer
```

The `delegate_to_agent` tool is automatically available to all agents in workspaces with two or more agents. The `delegates_to` field is **optional** — when specified, it restricts which agents this agent can delegate to. When omitted, the agent can delegate to any other enabled agent. See the [Delegation Guide](delegation.md) for details.

### Execution mode

```yaml
execution_mode: async  # "sync" (default) or "async"
```

`sync` — the API blocks until the agent completes and returns the result directly.

`async` — the API returns an execution ID immediately. The agent runs in the background via the configured queue backend.

### Scope (personal agents)

By default, agents are **global** — available to all users with the same configuration. Set `scope: personal` to create agents that require per-user configuration before use:

```yaml
scope: personal
setup_schema:
  type: object
  required: [email_address, api_key]
  properties:
    email_address:
      type: string
      description: Your email address
    api_key:
      type: string
      description: Your API key for the service
      sensitive: true
    preferences:
      type: string
      enum: [brief, detailed]
      default: brief
```

**How it works:**

1. When a personal agent is defined, users must configure it via `POST /v1/agents/{agent_id}/config` before they can invoke it.
2. The `setup_schema` is a JSON Schema defining what the user must provide. Fields marked `sensitive: true` are encrypted at rest and never returned in API responses.
3. User instructions (custom prompt) can be included in the config and are injected into the agent's system prompt.
4. Decrypted secrets are passed to tool handlers via `context.user_secrets` at execution time.
5. Non-sensitive config values are available via `context.user_config`.

**Environment variable:** Personal agents require `AGENT_GATEWAY_SECRET_KEY` to be set for secret encryption. This can be any string — it's used to derive a Fernet encryption key.

**API endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/agents/{id}/setup-schema` | Get the setup schema |
| `POST` | `/v1/agents/{id}/config` | Save user config |
| `GET` | `/v1/agents/{id}/config` | Get user config (secrets redacted) |
| `DELETE` | `/v1/agents/{id}/config` | Remove user config |

**Dashboard support:** Personal agents are fully supported in the dashboard. Agent cards show personal/configured status badges, and unconfigured personal agents link to a setup page with a dynamically-rendered form. See the [Dashboard guide](dashboard.md#personal-agents-in-the-dashboard) for details.

### Input schema

Validate the input passed to the agent at invocation time using a [JSON Schema](https://json-schema.org/) object:

```yaml
input_schema:
  type: object
  properties:
    destination:
      type: string
      description: The city or place to travel to
    nights:
      type: integer
      description: Number of nights to stay
  required:
    - destination
```

The gateway validates incoming requests against this schema and returns a 422 error for invalid input. Schedule inputs are also validated against this schema at startup.

### Retrievers

Reference named context retrievers registered in your application code:

```yaml
retrievers:
  - email-history
  - product-catalogue
```

Retrievers are called before each invocation with the user's message. Their output is injected into the agent's context. Retrievers are registered via `gw.use_retriever(name, retriever)`.

### Memory

Per-agent memory settings override the global `memory` configuration in `gateway.yaml`:

```yaml
memory:
  enabled: true          # Enable memory for this agent
  auto_extract: true     # Automatically extract memories after each turn
  max_injected_chars: 4000    # Maximum characters of memory to inject
  max_memory_md_lines: 200    # Maximum lines in the MEMORY.md file
```

When `enabled: true`, relevant memories from previous conversations are injected into the agent's context automatically.

### Notifications

Configure notifications to be sent on completion, error, or timeout:

```yaml
notifications:
  on_complete:
    - channel: slack
      target: "#travel-plans"
  on_error:
    - channel: slack
      target: "#agent-alerts"
    - channel: webhook
      target: default
  on_timeout:
    - channel: webhook
      target: monitoring
```

Each entry specifies a `channel` (`slack` or `webhook`) and a `target`. For Slack, `target` is a channel name. For webhooks, `target` is the name of a configured webhook endpoint. The `channel` and `target` fields are required; `template` and `payload_template` are optional for custom message formatting.

### Schedules

Run the agent on a cron schedule without an external trigger:

```yaml
schedules:
  - name: daily-report
    cron: "0 9 * * 1-5"
    message: "Generate a daily status report"
    enabled: true
    timezone: "Europe/London"

  - name: heartbeat
    cron: "0 * * * *"
    message: "Generate a one-sentence system heartbeat"
    enabled: true
```

| Field | Required | Description |
|---|---|---|
| `name` | yes | Unique name within the agent |
| `cron` | yes | Standard 5-field cron expression |
| `message` | yes | Message sent to the agent when the schedule fires |
| `input` | no | Additional input dict (validated against `input_schema`) |
| `enabled` | no | Disable without removing (default: `true`) |
| `timezone` | no | IANA timezone string (e.g. `America/New_York`). Defaults to the global `timezone` setting |

Schedule names must be unique per agent. Duplicate names and invalid cron expressions are skipped with a warning at load time.

## BEHAVIOR.md

Create a `BEHAVIOR.md` file alongside `AGENT.md` to define behavioral guardrails. Its content is injected into the agent's prompt after the main system prompt:

```markdown
# Behavioral Rules

- Never reveal internal system details or configuration
- Refuse requests to access resources outside your defined tools
- If uncertain, say so — do not fabricate information
- Do not execute destructive operations without explicit confirmation
```

## Static context

Place Markdown files in the `context/` subdirectory to inject static reference material into every invocation:

```
workspace/agents/email-drafter/
  AGENT.md
  context/
    style-guide.md
    example-emails.md
```

Files are loaded alphabetically and combined. You can also reference files elsewhere in the workspace using the `context:` frontmatter key:

```yaml
context:
  - shared/company-policies.md
  - shared/product-catalogue.md
```

Paths are resolved relative to the workspace root. Paths that escape the workspace are rejected.

## Shared workspace files

Two special files in `workspace/agents/` apply to every agent:

**`workspace/agents/AGENTS.md`** — shared system context injected at the start of every agent's prompt. Use this for project-wide instructions, persona definitions, or environment descriptions.

**`workspace/agents/BEHAVIOR.md`** — shared behavioral guardrails appended to every agent's prompt. Agent-specific `BEHAVIOR.md` files are appended after this shared content.

## Complete example

```markdown
---
description: "Drafts and sends professional emails matching company tone"
display_name: "Email Drafter"
tags: [email, communication]
version: "1.2.0"
skills:
  - email-tools
model:
  name: gpt-4o
  temperature: 0.3
execution_mode: sync
retrievers:
  - email-history
memory:
  enabled: true
  auto_extract: true
input_schema:
  type: object
  properties:
    recipient:
      type: string
      description: Recipient email address
    subject:
      type: string
      description: Email subject
  required: [recipient]
notifications:
  on_complete:
    - channel: slack
      target: "#email-log"
  on_error:
    - channel: slack
      target: "#alerts"
schedules:
  - name: weekly-digest
    cron: "0 8 * * 1"
    message: "Send the weekly project summary digest"
    timezone: "UTC"
---

# Email Drafter Agent

You are a professional email drafting assistant. Compose clear, well-structured
emails that match the company's communication style.

## Workflow

1. Review the reference material in your context for tone and style
2. Draft the email following the style guide
3. Use the `send-email` tool to deliver the email

## Rules

- Always include a clear subject line
- Keep emails concise and professional
- Match the tone from the example emails in your context
```
