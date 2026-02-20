---
status: complete
priority: p3
issue_id: "028"
tags: [code-review, simplicity, yagni]
dependencies: []
---

# Remove unused `RetrieverRegistry.has()` method

## Problem Statement

`RetrieverRegistry.has()` at `src/agent_gateway/context/registry.py:45-47` is only used in its own test. No production code calls it. Cross-reference validation uses frozenset membership. This is a YAGNI violation.

## Proposed Solutions

Remove `has()` and its test. It's a one-liner wrapping `in` on a dict.

- **Effort:** Small
- **Risk:** None
