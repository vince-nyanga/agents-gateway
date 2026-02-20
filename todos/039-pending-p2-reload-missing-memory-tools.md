---
status: pending
priority: p2
issue_id: "039"
tags: [code-review, architecture, functional-gap]
dependencies: []
---

# reload() Does Not Re-register Memory Tools

## Problem Statement
`Gateway.reload()` at `gateway.py:1215-1249` rebuilds the workspace and tool registry but does not re-register memory tools. If an agent adds or removes `memory.enabled: true` in AGENT.md, a reload will not pick up the change.

## Findings
- **Architecture reviewer**: P2 — functional gap users will encounter in production
- Memory initialization logic from `_startup()` step 7.2 needs to be replicated in `reload()`

## Proposed Solutions

### Option A: Extract memory tool registration into shared method
Move the step 7.2 memory init logic into a private `_register_memory_tools()` method, call from both `_startup()` and `reload()`.
- **Effort**: Medium | **Risk**: Low

## Acceptance Criteria
- [ ] Memory tools re-registered on reload
- [ ] Agent memory config changes picked up on reload
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
