---
status: pending
priority: p1
issue_id: "012"
tags: [code-review, bug, cli]
dependencies: []
---

# check.py tool_count variable shadowing regression

## Problem Statement

In `src/agent_gateway/cli/check.py`, the `tool_count` variable is reassigned inside a loop when computing tools from skills, causing the final count to reflect only the last agent's tool count rather than the total.

## Findings

- **Source**: kieran-python-reviewer
- **Severity**: P1 — CRITICAL (regression bug producing wrong output)
- **File**: `src/agent_gateway/cli/check.py`

## Proposed Solutions

### Option A: Use a separate accumulator variable
- **Pros**: Minimal change, clear intent
- **Cons**: None
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] `tool_count` in check.py correctly sums tools across all agents
- [ ] CLI `check` command reports accurate totals
- [ ] Tests verify correct output

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | Variable shadowing in loops |

## Resources

- PR #22
