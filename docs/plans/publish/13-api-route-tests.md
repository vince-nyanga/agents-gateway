---
title: "API Route Unit Tests"
status: completed
priority: P1
category: Testing
date: 2026-02-22
---

# API Route Unit Tests

## Problem

API routes (`src/agent_gateway/api/routes/`) have no dedicated unit tests. They're tested indirectly through integration tests, but error paths, edge cases, and response formatting are not covered.

## Files to Change

- `tests/test_api/` — New test directory with files for each route module

## Plan

1. Create `tests/test_api/` directory mirroring routes:
   - `test_invoke.py` — Test sync/async dispatch, input validation, timeout handling, streaming flag
   - `test_chat.py` — Test session creation, message validation, streaming response
   - `test_executions.py` — Test pagination, filtering, 404 for missing executions
   - `test_introspection.py` — Test agent/skill/tool listing
   - `test_schedules.py` — Test CRUD operations, pause/resume/trigger
   - `test_health.py` — Test health check response
   - `test_errors.py` — Test all error response formatting and status codes
2. Use `httpx.AsyncClient` with `TestClient` pattern
3. Mock `Gateway` internals to test route logic in isolation
4. Verify proper HTTP status codes, response schemas, and error payloads
5. Target: all routes have tests for happy path + at least 2 error paths
