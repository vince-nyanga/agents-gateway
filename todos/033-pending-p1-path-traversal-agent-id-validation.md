---
status: pending
priority: p1
issue_id: "033"
tags: [code-review, security, input-validation]
dependencies: []
---

# Path Traversal via agent_id in File Backend

## Problem Statement
`FileMemoryRepository._memory_path()` at `backends/file.py:51-52` uses `agent_id` directly in path construction with no validation. Values like `../../etc` could resolve outside the workspace directory. Additionally, `_write_records()` calls `path.parent.mkdir(parents=True)`, which would create arbitrary directories.

## Findings
- **Security reviewer**: HIGH severity — read/write arbitrary files possible
- Under normal conditions `agent_id` comes from workspace directory names, but public APIs accept arbitrary strings

## Proposed Solutions

### Option A: Regex validation + resolved path check (Recommended)
```python
import re
_SAFE_AGENT_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

def _memory_path(self, agent_id: str) -> Path:
    if not _SAFE_AGENT_ID.match(agent_id):
        raise ValueError(f"Invalid agent_id: {agent_id!r}")
    path = self._root / "agents" / agent_id / "MEMORY.md"
    if not path.resolve().is_relative_to(self._root.resolve()):
        raise ValueError(f"Path traversal detected for agent_id: {agent_id!r}")
    return path
```
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] agent_id validated with safe identifier regex
- [ ] Defense-in-depth resolved path check added
- [ ] Test added for path traversal attempt
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
