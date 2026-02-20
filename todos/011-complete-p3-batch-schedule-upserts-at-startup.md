---
status: complete
priority: p3
issue_id: "011"
tags: [code-review, performance, scheduler]
dependencies: []
---

# Batch Schedule Upserts at Startup (O(N) Sequential DB Round-Trips)

## Problem Statement

`_sync_schedule_records` upserts each schedule one at a time. Each upsert does SELECT + INSERT/UPDATE + COMMIT. For N schedules on remote PostgreSQL at 5ms per round-trip: `N * 3 * 5ms`. At 1000 schedules, that's 15 seconds of startup delay.

## Findings

**Found by:** performance-oracle

**Location:** `src/agent_gateway/scheduler/engine.py:159-181`

## Proposed Solutions

Use `session.merge()` in a single transaction with `upsert_batch()` method.

- **Effort:** Medium
- **Risk:** Low
- Acceptable for initial release if schedule counts stay under ~50

## Acceptance Criteria

- [ ] Schedule records are batch-upserted in a single transaction

## Work Log

- 2026-02-20: Identified during code review
