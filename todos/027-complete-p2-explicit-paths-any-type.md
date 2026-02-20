---
status: pending
priority: p2
issue_id: "027"
tags: [code-review, types, quality]
dependencies: []
---

# Narrow `_load_context_files` parameter type from `Any` to `list[str]`

## Problem Statement

The `explicit_paths` parameter in `_load_context_files` at `src/agent_gateway/workspace/agent.py:177` is typed as `Any`, violating the project's strict mypy convention. The function already validates internally, but the caller should narrow the type first.

## Proposed Solutions

### Solution A: Validate at call site, pass `list[str]`

```python
# In AgentDefinition.load():
raw_context = agent_meta.get("context", [])
context_paths: list[str] = raw_context if isinstance(raw_context, list) else []
context_content = _load_context_files(agent_dir, context_paths)
```

Then type the parameter as `list[str]` and remove the isinstance check inside `_load_context_files`.

- **Effort:** Small
- **Risk:** None

## Acceptance Criteria

- [ ] `_load_context_files` parameter typed as `list[str]`
- [ ] Validation moved to caller in `AgentDefinition.load()`
- [ ] mypy passes
