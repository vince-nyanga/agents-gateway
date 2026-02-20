---
status: pending
priority: p2
issue_id: "016"
tags: [code-review, security, workflow]
dependencies: []
---

# Sanitize exception details in workflow error responses

## Problem Statement

Workflow error dicts include raw `{e}` exception messages which may leak internal details (file paths, stack traces, connection strings) to API consumers.

## Findings

- **Source**: security-sentinel
- **Files**: `src/agent_gateway/engine/workflow.py` — `_run_tool()`, `_execute_parallel_step()`, `_execute_prompt_step()`

## Proposed Solutions

### Option A: Log full exception, return generic message
Log `str(e)` at ERROR level, return `{"error": "Tool '<name>' failed"}` without the raw exception.
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] Error dicts do not include raw exception messages
- [ ] Full details still available in logs

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | |

## Resources

- PR #22
