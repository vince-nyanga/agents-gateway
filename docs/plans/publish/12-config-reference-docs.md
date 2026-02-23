---
title: "Configuration Reference Docs"
status: completed
priority: P1
category: Documentation
date: 2026-02-22
---

# Configuration Reference Docs

## Problem

20+ configuration classes with no documentation. Users have no way to discover available options, understand defaults, or know which environment variables to set. The `AGENT_GATEWAY_` prefix and `__` nesting delimiter are undocumented.

## Files to Change

- Part of docs site (#6), specifically `docs/guides/configuration.md` and `docs/api-reference/configuration.md`

## Plan

1. Generate a configuration reference from the Pydantic models:
   - List every config key, its type, default value, and description
   - Show the corresponding environment variable name
   - Group by section (server, model, auth, persistence, queue, etc.)
2. Provide example `gateway.yaml` files for common scenarios:
   - Local development (SQLite, no auth, console telemetry)
   - Production (PostgreSQL, OAuth2, OTLP telemetry, Redis queue)
   - Minimal (just agents, no extras)
3. Document the env var resolution: prefix `AGENT_GATEWAY_`, nesting with `__`, `${VAR}` syntax in YAML
