---
title: "Agent-to-Agent Communication & Handover"
status: completed
priority: P1
category: Feature
date: 2026-02-22
---

# Agent-to-Agent Communication & Handover

## Problem

Agents operate in isolation. There is no way for one agent to delegate work to another agent, pass results, or orchestrate multi-agent workflows. In real business scenarios, a "research agent" might need to hand results to an "analysis agent" which then passes to a "report writer agent." The entire chain must be traceable as a single workflow with full cost visibility.

## What Exists Today

- Skills can compose multiple tools in a workflow (sequential + parallel steps)
- ExecutionRecord tracks individual agent runs with execution_id
- Tools receive `ToolContext` with execution_id and agent_id
- No concept of one agent invoking another

## Concepts

- **Agent delegation**: An agent can call another agent as if it were a tool — via a built-in `delegate_to_agent` tool that is automatically available when configured
- **Delegation chain**: Each delegation creates a child execution linked to the parent via `parent_execution_id`, forming a tree of executions
- **Workflow tracing**: The root execution_id is carried through the entire chain as `root_execution_id`, so the full workflow can be queried as a unit
- **Cost rollup**: Total cost for a workflow = sum of all executions sharing the same `root_execution_id`
- **Delegation policy**: Agents declare which other agents they can delegate to in AGENT.md frontmatter (`delegates_to: [agent-a, agent-b]`), preventing unbounded chains
- **Max depth**: A configurable guardrail limits delegation depth (default: 3) to prevent infinite loops

## Files to Change

**New files:**
- `src/agent_gateway/engine/delegation.py` — Delegation tool implementation
- `tests/test_engine/test_delegation.py` — Delegation tests

**Modified files:**
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

## Plan

### Phase 1 — Execution lineage model
1. Add fields to `ExecutionRecord`:
   ```
   parent_execution_id: str | None   # direct parent (who delegated to me)
   root_execution_id: str | None     # root of the entire workflow tree
   delegation_depth: int = 0         # depth in the delegation tree
   ```
2. Add indexes on `parent_execution_id` and `root_execution_id`
3. Add `delegates_to: list[str] = []` to `AgentDefinition` frontmatter parsing
4. Add `max_delegation_depth: int = 3` to `GuardrailsConfig`

### Phase 2 — Delegation tool
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

### Phase 3 — Tracing & cost rollup
10. Add `ExecutionRepository.list_by_root_execution(root_execution_id)` — returns all executions in a workflow tree
11. Add `ExecutionRepository.cost_by_root_execution(root_execution_id)` — aggregated cost across the tree
12. Add `GET /v1/executions/{execution_id}/workflow` — returns the full execution tree with relationships
13. Add `?root_execution_id=` filter to `GET /v1/executions`

### Phase 4 — Dashboard visualization
14. Add workflow trace view to execution detail page:
    - Tree visualization showing delegation chain (parent → children)
    - Each node shows: agent_id, status, duration, cost, input/output summary
    - Total workflow cost, total duration, total tokens at the top
15. Link parent/child executions bidirectionally in the execution detail page
16. Add "Workflow" badge on executions that are part of a delegation chain

### Phase 5 — Testing & example
17. Unit tests: delegation tool, depth limits, permission checks, execution lineage queries
18. Integration tests: A → B → C delegation chain with full tracing
19. Update example project with a multi-agent workflow (e.g., "research" → "analyze" → "report")

## AGENT.md Example

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
