---
status: complete
priority: p3
issue_id: "021"
tags: [code-review, workflow, extensibility]
dependencies: []
---

# Make prompt step system message configurable

## Problem Statement

The system prompt in `_execute_prompt_step` is hardcoded as `"You are a workflow step. Respond concisely."`. This should be configurable per-skill or per-step.

## Findings

- **Source**: kieran-python-reviewer
- **File**: `src/agent_gateway/engine/workflow.py`

## Acceptance Criteria

- [ ] System prompt can be overridden via skill or step config
- [ ] Default behavior unchanged

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | |
