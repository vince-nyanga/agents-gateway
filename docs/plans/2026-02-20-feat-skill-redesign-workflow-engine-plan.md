---
title: "feat: Redesign skills as workflow orchestration units"
type: feat
status: active
date: 2026-02-20
---

# feat: Redesign skills as workflow orchestration units

## Overview

Redesign skills from simple prompt-fragment containers into composable workflow units that own tools and support multi-step orchestration. This creates a clean three-layer separation:

| File | Purpose |
|------|---------|
| `AGENT.md` | Identity — who the agent is, what skills it has |
| `BEHAVIOR.md` | Guardrails — behavioral rules, tone, constraints |
| `SKILL.md` | Capabilities — tools + orchestration instructions |

After this change, **tools are no longer declared directly on agents**. Agents reference skills, skills own tools. The `tools:` key moves from AGENT.md to SKILL.md exclusively.

## Problem Statement

**Current model:** Skills are thin wrappers — a prompt fragment plus a list of tool names. Agents independently declare both `skills:` and `tools:` in their frontmatter. This creates:

1. **Duplicated tool declarations** — the same tool often appears in both a skill's `tools:` list and an agent's `tools:` list.
2. **No clear ownership** — tools float freely between agents and skills with no single source of truth.
3. **No orchestration** — skills are just prompt text. There's no way to express multi-step workflows, parallel execution, or conditional logic beyond "write it in prose and hope the LLM follows."
4. **Flat capability model** — callers invoke agents, not capabilities. There's no way to say "run the lead-qualification skill on this agent."

## Proposed Solution

### Three skill roles

Skills serve three complementary purposes:

1. **Prompt fragments** — Reusable instructions shared across agents (existing behavior, preserved).
2. **Tool owners** — Every tool belongs to exactly one skill. Agents gain tools by referencing skills.
3. **Workflow orchestration** — Skills can define multi-step execution plans with sequencing, parallel fan-out, and fan-in aggregation.

### New SKILL.md format

```yaml
---
name: lead-qualification
description: Qualifies sales leads using enrichment and scoring
tools:
  - enrich-company
  - score-lead
  - lookup-crm
steps:              # Optional — if omitted, tools are available ad-hoc (current behavior)
  - name: enrich
    tool: enrich-company
    input: { company: "$.input.company_name" }
  - name: score
    tools:          # Parallel fan-out
      - tool: score-lead
        input: { data: "$.steps.enrich.output" }
      - tool: lookup-crm
        input: { domain: "$.input.domain" }
  - name: decide
    prompt: >
      Given the enrichment data and CRM lookup, determine if this lead
      is qualified. Return { "qualified": true/false, "reason": "..." }.
    input:
      enrichment: "$.steps.enrich.output"
      crm_data: "$.steps.score[1].output"
      lead_score: "$.steps.score[0].output"
---

# Lead Qualification

When asked to qualify a lead, use the structured workflow above.
For ad-hoc questions about leads, use the tools directly.
```

### Agent references skills only

```yaml
# AGENT.md
---
skills:
  - lead-qualification
  - email-drafting
# No more tools: key
---
```

### API-level skill invocation (future consideration)

```
POST /v1/agents/{id}/invoke
{
  "message": "Qualify this lead",
  "skill": "lead-qualification",    # Optional — hints which skill to use
  "input": { "company_name": "Acme", "domain": "acme.com" }
}
```

## Acceptance Criteria

### Phase 1: Move tools from AGENT.md to SKILL.md

- [ ] Remove `tools:` key from AGENT.md frontmatter parsing in `agent.py`
- [ ] Remove `tools` field from `AgentDefinition` dataclass
- [ ] Update `ExecutionEngine._resolve_skill_tools()` — this is now the only tool source
- [ ] Update `ToolRegistry.resolve_for_agent()` — remove `direct_tool_names` parameter
- [ ] Update all agents in example project to remove `tools:` from AGENT.md, ensure tools are in skill definitions
- [ ] Update test fixtures — move tool declarations from AGENT.md to SKILL.md
- [ ] Update cross-reference validation in `loader.py` — warn if AGENT.md still has `tools:`
- [ ] All existing tests pass (or are updated)

### Phase 2: Workflow step model

- [ ] Define `SkillStep` dataclass in `skill.py` with fields: `name`, `tool`/`tools`, `prompt`, `input`
- [ ] Parse `steps:` from SKILL.md frontmatter into `SkillDefinition.steps`
- [ ] Add JSON-path-like input resolution (`$.input.*`, `$.steps.<name>.output`)
- [ ] Skills without `steps:` work exactly as today (ad-hoc tool access)

### Phase 3: Workflow executor

- [ ] Add `WorkflowExecutor` class that runs skill steps in order
- [ ] Sequential steps: run one at a time, pass output forward
- [ ] Parallel steps: fan-out when `tools:` is a list, fan-in results
- [ ] Prompt steps: call LLM with assembled context (no tool call)
- [ ] Integrate with existing `ExecutionEngine` — workflow executor calls back into engine for LLM/tool calls
- [ ] Add timeout and error handling per step

### Phase 4: Test coverage

- [ ] Unit tests for step parsing
- [ ] Unit tests for input resolution (`$.input.*`, `$.steps.*`)
- [ ] Integration tests for sequential workflow execution
- [ ] Integration tests for parallel fan-out/fan-in
- [ ] Integration tests for prompt-only steps
- [ ] Test that skills without steps work identically to current behavior
- [ ] Update all existing skill tests

### Phase 5: Documentation and example project

- [ ] Update DESIGN.md with new skill model
- [ ] Update CLAUDE.md conventions
- [ ] Add a workflow skill to the example project (e.g., travel-planning workflow)
- [ ] Update example project README
- [ ] Update CLI output for `agent-gateway skills` to show step count

### Shared

- [ ] All tests pass (`uv run pytest -m "not e2e"`)
- [ ] Linting clean (`uv run ruff check src/ tests/`)
- [ ] Type checking clean (`uv run mypy src/`)
- [ ] Example project works (`make dev`)

## Implementation Phases

### Phase 1: Move tools from AGENT.md to SKILL.md

This is the breaking structural change. After this phase, agents no longer own tools directly.

**File: `src/agent_gateway/workspace/agent.py`**

1. Remove `tools` field from `AgentDefinition`:
   ```python
   # BEFORE
   tools: list[str] = field(default_factory=list)

   # AFTER — field removed entirely
   ```

2. Remove `tools` parsing from `load()`:
   ```python
   # DELETE
   tools = agent_meta.get("tools", [])
   ```

3. If `tools:` found in frontmatter, log a deprecation warning pointing to SKILL.md.

**File: `src/agent_gateway/engine/executor.py`**

1. Update `_resolve_skill_tools()` — this becomes the sole tool source:
   ```python
   def _resolve_skill_tools(self, agent: AgentDefinition, workspace: WorkspaceState) -> list[str]:
       tool_names: list[str] = []
       for skill_name in agent.skills:
           skill = workspace.skills.get(skill_name)
           if skill:
               tool_names.extend(skill.tools)
       return tool_names
   ```

2. Update `execute()` — remove `agent.tools` from resolve call:
   ```python
   # BEFORE
   resolved_tools = self._registry.resolve_for_agent(agent.id, skill_tool_names, agent.tools)

   # AFTER
   resolved_tools = self._registry.resolve_for_agent(agent.id, skill_tool_names)
   ```

**File: `src/agent_gateway/workspace/registry.py`**

1. Simplify `resolve_for_agent()`:
   ```python
   # BEFORE
   def resolve_for_agent(self, agent_id, skill_tool_names, direct_tool_names) -> list[ResolvedTool]:
       needed_names = set(skill_tool_names) | set(direct_tool_names)

   # AFTER
   def resolve_for_agent(self, agent_id, tool_names: list[str]) -> list[ResolvedTool]:
       needed_names = set(tool_names)
   ```

**File: `src/agent_gateway/api/routes/introspection.py`**

1. Update `AgentInfo` response model — remove `tools` field (or compute it from skills).

**Fixture and example updates:**

- Move `tools: [echo]` from test fixture AGENT.md to test-skill SKILL.md
- Update example project agents — move tool declarations to their skills
- Create new skills in example project as needed to own orphaned tools

### Phase 2: Workflow step model

**File: `src/agent_gateway/workspace/skill.py`**

1. Add step dataclasses:
   ```python
   @dataclass
   class ToolStep:
       """A single tool invocation in a workflow."""
       tool: str
       input: dict[str, str] = field(default_factory=dict)  # JSONPath-like refs

   @dataclass
   class SkillStep:
       """One step in a skill workflow."""
       name: str
       tool: str | None = None            # Single tool
       tools: list[ToolStep] | None = None # Parallel fan-out
       prompt: str | None = None           # LLM-only step
       input: dict[str, str] = field(default_factory=dict)
   ```

2. Add `steps` field to `SkillDefinition`:
   ```python
   steps: list[SkillStep] = field(default_factory=list)
   ```

3. Parse `steps:` from frontmatter in `load()`.

**File: `src/agent_gateway/engine/resolver.py`** (new)

1. Implement `resolve_input(template: dict, context: dict) -> dict` — resolve JSONPath references like `$.input.company_name` and `$.steps.enrich.output` against a runtime context.

### Phase 3: Workflow executor

**File: `src/agent_gateway/engine/workflow.py`** (new)

```python
class WorkflowExecutor:
    """Executes a skill's step-based workflow."""

    async def execute(
        self,
        skill: SkillDefinition,
        input_data: dict[str, Any],
        tool_executor: ToolExecutorFn,
        llm_client: LLMClient,
        context: ToolContext,
    ) -> dict[str, Any]:
        """Run all steps, returning aggregated results."""
```

The workflow executor:
- Maintains a context dict: `{"input": input_data, "steps": {}}`
- For each step:
  - Resolves input templates against context
  - Executes tool(s) or LLM prompt
  - Stores output in `context["steps"][step.name]`
- Returns the final step's output

Integration point: `ExecutionEngine.execute()` detects when the LLM selects a skill with steps and delegates to `WorkflowExecutor`.

### Phase 4–5: Tests and documentation

Standard test and docs updates. See acceptance criteria.

## Risk Analysis

**Medium risk.** This is a larger change than the CONFIG.md removal.

- **Phase 1 is the riskiest** — removing `tools:` from agents is a breaking change to the workspace format. Mitigated by being pre-1.0.
- **Phase 2–3 are additive** — new functionality, no existing behavior changes.
- **Workflow execution adds complexity** — step resolution, parallel execution, error handling. Keep it simple: start with sequential-only, add parallel in a follow-up if needed.

**Footgun to avoid:** The `@gw.tool()` decorator registers tools globally. These code-registered tools still need to be accessible — they don't live in SKILL.md. Ensure `ToolRegistry` continues to resolve code tools even without a skill reference. One approach: code tools are always available to any agent (current behavior for tools with no `allowed_agents`).

**Simplification option:** Phase 2–3 (workflow steps) could be deferred to a separate PR. Phase 1 alone (moving tools to skills) is valuable and self-contained.

## References

- Agent parser: `src/agent_gateway/workspace/agent.py`
- Skill parser: `src/agent_gateway/workspace/skill.py`
- Tool registry: `src/agent_gateway/workspace/registry.py`
- Execution engine: `src/agent_gateway/engine/executor.py`
- Prompt assembly: `src/agent_gateway/workspace/prompt.py`
- Workspace loader: `src/agent_gateway/workspace/loader.py`
- API routes: `src/agent_gateway/api/routes/introspection.py`
- CLI: `src/agent_gateway/cli/`
- Example skills: `examples/test-project/workspace/skills/`
- Example agents: `examples/test-project/workspace/agents/`
- Test fixtures: `tests/fixtures/workspace/`
