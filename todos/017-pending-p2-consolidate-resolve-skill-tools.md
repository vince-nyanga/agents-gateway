---
status: pending
priority: p2
issue_id: "017"
tags: [code-review, architecture, duplication]
dependencies: []
---

# Consolidate duplicated _resolve_skill_tools logic

## Problem Statement

Tool resolution from skills is duplicated between `introspection.py:_resolve_agent_tools()` and `executor.py`. Both walk agent.skills → skill.tools to build a tool list.

## Findings

- **Source**: kieran-python-reviewer, architecture-strategist
- **Files**: `src/agent_gateway/api/routes/introspection.py`, `src/agent_gateway/engine/executor.py`

## Proposed Solutions

### Option A: Add method to AgentDefinition or WorkspaceState
`workspace.resolve_tools_for_agent(agent_id) -> list[str]` as a single source of truth.
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] Single function used by both introspection and executor
- [ ] No behavioral change

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | |

## Resources

- PR #22
