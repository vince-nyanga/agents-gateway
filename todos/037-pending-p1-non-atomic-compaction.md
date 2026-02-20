---
status: pending
priority: p1
issue_id: "037"
tags: [code-review, data-integrity, architecture]
dependencies: []
---

# Non-Atomic Compaction — Data Loss Risk

## Problem Statement
At `manager.py:244-248`, compaction calls `delete_all()` then saves new records in a loop. The comment says "Transactional" but it is not. If the process crashes between delete and save, all memories are lost. The `old_ids` variable is computed but never used for rollback.

## Findings
- **Python reviewer**: P1 — data loss on partial failure
- **Architecture reviewer**: P1 — misleading "transactional" comment
- **Security reviewer**: MEDIUM — non-atomic operation

## Proposed Solutions

### Option A: Write-then-delete (Recommended)
Save new records first, then delete old ones. This way a crash leaves duplicates rather than data loss.
- **Effort**: Small | **Risk**: Low

### Option B: Fix comment + document for backend implementers
At minimum, correct the misleading "Transactional" comment and document that custom backends should wrap in a DB transaction.
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] Compaction reordered to save-then-delete, or comment corrected
- [ ] No data loss possible on partial failure
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
