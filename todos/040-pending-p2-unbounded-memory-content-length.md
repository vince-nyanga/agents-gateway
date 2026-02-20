---
status: pending
priority: p2
issue_id: "040"
tags: [code-review, security, input-validation]
dependencies: []
---

# Unbounded Memory Content in memory_save Tool

## Problem Statement
The `memory_save` tool at `tools.py` accepts content with no length validation. The JSON schema has no `maxLength` constraint. An LLM could save extremely large entries, leading to disk/memory exhaustion or context window overflow.

## Findings
- **Security reviewer**: MEDIUM — denial of service through resource exhaustion
- No content length validation in tool function or schema

## Proposed Solutions

### Option A: Add maxLength constraint (Recommended)
Add `"maxLength": 2000` to schema and validate in function body.
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] maxLength added to memory_save schema
- [ ] Content length validated in function
- [ ] Error returned for oversized content
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
