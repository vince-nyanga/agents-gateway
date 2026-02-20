---
status: complete
priority: p3
issue_id: "030"
tags: [code-review, quality, tests]
dependencies: []
---

# Extract shared test fakes into conftest.py

## Problem Statement

`_FakeRetriever` and `_FailingRetriever` are duplicated across `test_protocol.py`, `test_registry.py`, and `test_prompt_integration.py`. About 40 lines of duplication.

## Proposed Solutions

Add `tests/test_context/conftest.py` with shared `_FakeRetriever` and `_FailingRetriever` fixtures.

- **Effort:** Small
- **Risk:** None
