---
status: pending
priority: p2
issue_id: "025"
tags: [code-review, security, performance]
dependencies: []
---

# Add size limits on retriever output and static context files

## Problem Statement

Two related gaps:

1. **Dynamic retriever output** (`src/agent_gateway/workspace/prompt.py:93`): No limit on the number or size of chunks a retriever returns. A misbehaving retriever could return megabytes of text, causing context window overflow, excessive LLM costs, or silent truncation of important agent instructions.

2. **Static context files** (`src/agent_gateway/workspace/agent.py:201`): Files are read entirely into memory with no size cap. A large markdown file could consume the entire LLM context window.

## Findings

- **Retriever location:** `src/agent_gateway/workspace/prompt.py:93` — `results.extend(chunks)` with no bounds
- **Static location:** `src/agent_gateway/workspace/agent.py:201` — `entry.read_text()` with no size check
- **Plan document** (line 219) acknowledges this: "log a warning when total prompt size exceeds a configurable threshold (default: 50,000 chars)"
- **Discovered by:** security-sentinel, performance-oracle

## Proposed Solutions

### Solution A: Add configurable limits with truncation warnings

Add `MAX_RETRIEVED_CHARS` and `MAX_CONTEXT_FILE_SIZE` constants with warning logs on truncation.

- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] Retriever results capped at a reasonable total size (e.g., 50,000 chars)
- [ ] Static context files capped per-file (e.g., 100KB)
- [ ] Warning logged when truncation occurs
- [ ] Tests cover the truncation behavior
