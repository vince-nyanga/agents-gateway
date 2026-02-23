# Agent-to-Agent Delegation

Agent delegation allows one agent to hand off tasks to other agents, enabling multi-agent workflows with full execution lineage tracking.

## Overview

A **coordinator** agent can delegate subtasks to **specialist** agents using the built-in `delegate_to_agent` tool. Each delegation creates a child execution linked to the parent, forming a workflow tree with cost rollup.

## Configuration

### Agent Setup

Add `delegates_to` to an agent's `AGENT.md` frontmatter to specify which agents it can delegate to:

```yaml
---
description: "Project coordinator"
delegates_to:
  - researcher
  - writer
  - reviewer
---
```

The delegation tool (`delegate_to_agent`) is automatically registered for agents with `delegates_to` configured. No skill registration is needed.

### Guardrails

Control maximum delegation depth in `gateway.yaml`:

```yaml
guardrails:
  max_delegation_depth: 3  # default
```

This prevents infinite delegation loops. Each delegation increments the depth counter; when it reaches the maximum, further delegations are rejected.

## How It Works

1. The coordinator agent receives a request
2. It calls `delegate_to_agent` with a target agent ID and message
3. The gateway creates a child execution linked to the parent
4. The target agent processes the request and returns a result
5. The coordinator receives the result as a tool response
6. The coordinator can delegate to additional agents or produce a final response

### Delegation Tool Schema

The `delegate_to_agent` tool accepts:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | ID of the target agent |
| `message` | string | Yes | Task description for the target agent |
| `input` | object | No | Structured input for the target agent |

### Permission Model

- Agents can only delegate to agents listed in their `delegates_to` configuration
- Attempting to delegate to an unlisted agent returns an error message (not an exception)
- The delegation depth is enforced globally via `max_delegation_depth`

## Execution Lineage

Every execution in a delegation chain tracks:

- **`parent_execution_id`**: The direct parent that delegated to this execution
- **`root_execution_id`**: The root of the entire workflow tree
- **`delegation_depth`**: How deep in the delegation tree this execution is

### API Endpoints

**Get workflow tree:**
```
GET /v1/executions/{execution_id}/workflow
```
Returns all executions in the delegation tree, ordered by depth and creation time.

**Filter by root execution:**
```
GET /v1/executions?root_execution_id={id}
```
Returns all executions belonging to a specific workflow tree.

### Dashboard

The execution detail page in the dashboard shows:
- A link to the parent execution (if delegated)
- A list of child executions (if this execution delegated to others)
- Total workflow cost rollup for root executions
- A "Workflow" badge for executions that are part of a delegation chain

## Example

### Coordinator Agent (`workspace/agents/coordinator/AGENT.md`)

```yaml
---
description: "Coordinator that orchestrates research and writing"
delegates_to:
  - researcher
  - writer
---
```

```markdown
# Coordinator

You coordinate research and writing tasks.

When asked to create a report:
1. Delegate research to the researcher agent
2. Use the research results to delegate writing to the writer agent
3. Review and present the final output
```

### Specialist Agent (`workspace/agents/researcher/AGENT.md`)

```yaml
---
description: "Research specialist"
---
```

```markdown
# Researcher

You gather and analyze information on requested topics.
Provide structured, well-organized research summaries.
```

### Programmatic Usage

```python
from agent_gateway import Gateway

async with Gateway(workspace="./workspace") as gw:
    result = await gw.invoke("coordinator", "Create a report on AI trends")
    # The coordinator will delegate to researcher and writer automatically
```

## Cost Tracking

Delegation creates a tree of executions. The total workflow cost can be queried:

- **Dashboard**: Root executions show a "Total Workflow Cost" in the delegation panel
- **API**: Use `GET /v1/executions/{id}/workflow` and sum the usage across all executions
