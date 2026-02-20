---
status: pending
priority: p2
issue_id: "015"
tags: [code-review, security, performance, workflow]
dependencies: []
---

# Add max_parallel limit to workflow fan-out steps

## Problem Statement

A skill with a large `tools` list in a parallel step will spawn unbounded concurrent tasks. A malicious or misconfigured SKILL.md could exhaust resources.

## Findings

- **Source**: security-sentinel, performance-oracle
- **File**: `src/agent_gateway/engine/workflow.py` — `_execute_parallel_step()`

## Proposed Solutions

### Option A: Add max_parallel parameter with semaphore
Add a configurable limit (default 10) and use `asyncio.Semaphore` to throttle concurrent tool executions.
- **Effort**: Small
- **Risk**: Low

### Option B: Validate at parse time
Reject skills with more than N parallel tools during SKILL.md parsing.
- **Effort**: Small
- **Risk**: Low (but less flexible)

## Acceptance Criteria

- [ ] Parallel fan-out has a configurable concurrency limit
- [ ] Tests verify limit is respected

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | |

## Resources

- PR #22
