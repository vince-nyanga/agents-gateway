---
title: "Dashboard Filtering & Real-Time Updates"
status: completed
priority: P2
category: UX
date: 2026-02-22
---

# Dashboard Filtering & Real-Time Updates

## Problem

Dashboard execution list only filters by agent_id and status. No date range filter, no cost filter, no search. Execution list is static — no live updates for running executions. Conversations are not shown as grouped entities.

## Files to Change

- `src/agent_gateway/dashboard/router.py`
- `src/agent_gateway/dashboard/templates/executions.html`
- `src/agent_gateway/dashboard/models.py`
- `src/agent_gateway/persistence/backends/sql/repository.py`

## Plan

1. Add query parameters to execution listing: `date_from`, `date_to`, `min_cost`, `max_cost`
2. Add repository methods supporting these filters
3. Add HTMX polling on the executions page to refresh running executions (every 5s)
4. Add a "Conversations" view grouping executions by `session_id` with aggregated stats
5. Add execution detail link from conversation view
6. Consider adding full-text search on message/result content (PostgreSQL `ILIKE` or `tsvector`)
