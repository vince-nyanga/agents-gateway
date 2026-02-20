---
status: pending
priority: p2
issue_id: "018"
tags: [code-review, agent-native, api]
dependencies: []
---

# Add has_workflow and step_count to API SkillInfo model

## Problem Statement

The CLI shows skill step count but the API `SkillInfo` response model doesn't expose `has_workflow` or `step_count`. This breaks agent-native parity — an API consumer cannot discover workflow-capable skills.

## Findings

- **Source**: agent-native-reviewer
- **Files**: `src/agent_gateway/api/routes/introspection.py` (SkillInfo model)

## Proposed Solutions

### Option A: Add fields to SkillInfo
Add `has_workflow: bool` and `step_count: int` to the existing Pydantic response model.
- **Effort**: Small
- **Risk**: Low (additive API change)

## Acceptance Criteria

- [ ] GET /v1/skills returns `has_workflow` and `step_count` per skill
- [ ] Tests verify the new fields

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-20 | Created from PR #22 review | |

## Resources

- PR #22
