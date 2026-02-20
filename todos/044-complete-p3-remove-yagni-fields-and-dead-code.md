---
status: complete
priority: p3
issue_id: "044"
tags: [code-review, simplicity, yagni]
dependencies: []
---

# Remove YAGNI Fields and Dead Code

## Problem Statement
Several fields and classes exist that are never used or populated, adding unnecessary complexity.

## Findings
- **Simplicity reviewer**: Multiple YAGNI violations identified
- `access_count` on MemoryRecord — never incremented (domain.py:40)
- `metadata` on MemoryRecord — never populated or read (domain.py:38)
- `MemoryBackendError` — never raised (exceptions.py:77)
- `read_context_block()` on FileMemoryRepository — dead code, bypassed by Manager (file.py:195-220)
- `custom prompt overrides` (extraction_prompt, compaction_prompt) — never used by any consumer

## Proposed Solutions

### Option A: Remove all unused items (Recommended)
Delete access_count, metadata, MemoryBackendError, read_context_block, and custom prompt config fields.
- **Effort**: Medium | **Risk**: Low
- Estimated ~40 LOC removed

## Acceptance Criteria
- [ ] Unused fields removed from MemoryRecord
- [ ] MemoryBackendError removed
- [ ] read_context_block removed from FileMemoryRepository
- [ ] Custom prompt config removed
- [ ] Tests updated
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
