---
title: "OpenAPI Endpoint Documentation"
status: completed
priority: P1
category: API
date: 2026-02-22
---

# OpenAPI Endpoint Documentation

## Problem

Swagger UI at `/docs` shows endpoints but lacks descriptions, examples, response schemas, and scope requirements. Businesses evaluating the API have a poor experience in the interactive docs.

## Files to Change

- `src/agent_gateway/api/routes/invoke.py`
- `src/agent_gateway/api/routes/chat.py`
- `src/agent_gateway/api/routes/executions.py`
- `src/agent_gateway/api/routes/introspection.py`
- `src/agent_gateway/api/routes/schedules.py`
- `src/agent_gateway/api/routes/health.py`
- `src/agent_gateway/api/routes/status.py`
- `src/agent_gateway/api/models.py`

## Plan

1. Add `summary`, `description`, `tags`, and `responses` to every route decorator
2. Add `Field(description=..., examples=[...])` to all Pydantic request/response models
3. Add `response_model` to all endpoints for auto-generated response docs
4. Group endpoints with tags: "Agents", "Executions", "Sessions", "Schedules", "Admin"
5. Add 401/403/404/422/429 response schemas to all protected endpoints
6. Verify the generated OpenAPI spec is complete and accurate
