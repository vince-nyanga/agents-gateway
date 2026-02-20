---
status: complete
priority: p3
issue_id: "049"
tags: [code-review, agent-native, api]
dependencies: []
---

# Consider REST API Endpoints for Memory

## Problem Statement
Every major subsystem (executions, chat, schedules, introspection) has REST endpoints, but memory has none. External clients (dashboards, admin tools) cannot manage memory via HTTP.

## Findings
- **Agent-native reviewer**: Warning — significant parity gap for API-first framework
- Suggested endpoints: GET/POST /v1/agents/{id}/memories, DELETE /v1/agents/{id}/memories/{mid}

## Proposed Solutions

### Option A: Add REST endpoints in follow-up PR
Create memory API router with CRUD endpoints.
- **Effort**: Large | **Risk**: Low

### Option B: Defer until consumer demand
Document that memory is managed via tools and programmatic API only for v1.
- **Effort**: None | **Risk**: None

## Acceptance Criteria
- [ ] Decision made: add endpoints or defer
- [ ] If adding: endpoints implemented with tests
- [ ] If deferring: documented as future work

## Work Log
- 2026-02-20: Created from code review findings
