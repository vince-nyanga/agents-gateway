---
status: complete
priority: p3
issue_id: "045"
tags: [code-review, simplicity, yagni]
dependencies: []
---

# Consider Removing Compaction Machinery

## Problem Statement
The `compact()` method, `CompactionResult`, `MemoryCompactionError`, compaction prompt, and `compact_threshold`/`compact_target` config fields all exist but compaction is not wired up anywhere — no trigger, no API endpoint, no periodic task.

## Findings
- **Simplicity reviewer**: ~70 LOC of dead code across manager.py, domain.py, exceptions.py, config.py
- `save()` logs a warning at threshold but does not trigger compaction
- No consumer can currently invoke compaction except programmatically

## Proposed Solutions

### Option A: Remove all compaction machinery (Recommended)
Delete compact(), CompactionResult, MemoryCompactionError, threshold/target config. Ship compaction when there is a trigger.
- **Effort**: Medium | **Risk**: Low

### Option B: Wire up compaction with a trigger
Add auto-compact after save when threshold exceeded, or add an API endpoint.
- **Effort**: Medium | **Risk**: Medium

## Acceptance Criteria
- [ ] Compaction either removed or wired up end-to-end
- [ ] Tests updated accordingly
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
