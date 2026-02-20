---
status: complete
priority: p3
issue_id: "010"
tags: [code-review, simplicity, scheduler]
dependencies: []
---

# Remove YAGNI Methods (soft_delete, list_by_schedule, redundant schedules param)

## Problem Statement

Several methods and parameters are defined but never called from application code:
- `ScheduleRepository.soft_delete` - defined but never called
- `ExecutionRepository.list_by_schedule` - defined but never called
- `start(schedules=...)` parameter - `schedules` is only used for a count log, all data comes from `agents`

## Findings

**Found by:** code-simplicity-reviewer

## Proposed Solutions

Remove unused methods and simplify `start()` signature. ~20 LOC reduction.

- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] Remove `soft_delete` from protocol and implementations
- [ ] Remove `list_by_schedule` from protocol and implementations
- [ ] Remove `schedules` parameter from `start()` or compute count from `agents`

## Work Log

- 2026-02-20: Identified during code review
