---
status: pending
priority: p1
issue_id: "034"
tags: [code-review, security, example-code]
dependencies: []
---

# SQL Injection in pgvector Example via Table Name

## Problem Statement
`examples/test-project/pgvector_memory.py` interpolates the `table` parameter directly into SQL strings via f-strings throughout the entire class. Since this is the canonical reference for consumers building custom backends, they will copy this pattern.

## Findings
- **Security reviewer**: CRITICAL — full database compromise possible
- Every method uses `f"...{self.table}..."` for query construction
- Parameters are properly bound, but table name itself is injectable

## Proposed Solutions

### Option A: Add table name validation regex (Recommended)
```python
import re
_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")

def __post_init__(self):
    if not _SAFE_IDENT.match(self.table):
        raise ValueError(f"Unsafe table name: {self.table!r}")
```
- **Effort**: Small | **Risk**: Low

## Acceptance Criteria
- [ ] Table name validated in `__post_init__`
- [ ] Comment added: table must be a trusted identifier, never user input
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
