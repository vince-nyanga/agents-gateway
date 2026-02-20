---
status: complete
priority: p3
issue_id: "029"
tags: [code-review, simplicity, examples]
dependencies: []
---

# Deduplicate `EmailHistoryRetriever` across example scripts

## Problem Statement

`EmailHistoryRetriever` is copy-pasted between `examples/test-project/app.py` and `examples/test-project/serve_email.py` (26 lines of duplication). Also consider whether `serve_light.py` (unrelated to RAG) should be in this PR.

## Proposed Solutions

Extract `EmailHistoryRetriever` into a shared module (e.g., `examples/test-project/retrievers.py`) and import from both scripts. Remove or land `serve_light.py` separately.

- **Effort:** Small
- **Risk:** None
