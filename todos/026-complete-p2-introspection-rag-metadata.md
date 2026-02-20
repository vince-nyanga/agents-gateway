---
status: pending
priority: p2
issue_id: "026"
tags: [code-review, agent-native, api]
dependencies: []
---

# Expose retriever and context metadata in AgentInfo introspection

## Problem Statement

The `AgentInfo` response model at `src/agent_gateway/api/models.py:112-127` does not include `retrievers` or context metadata. An API consumer (including an orchestrating agent) calling `GET /v1/agents` cannot discover which agents have RAG context or which retrievers they use.

## Findings

- **Location:** `src/agent_gateway/api/models.py` (AgentInfo), `src/agent_gateway/api/routes/introspection.py:51-79`
- **Gap:** `retrievers: list[str]` and `has_context: bool` / `context_file_count: int` not exposed
- **Discovered by:** agent-native-reviewer

## Proposed Solutions

### Solution A: Add fields to AgentInfo (Recommended)

Add `retrievers: list[str] = Field(default_factory=list)` and `context_file_count: int = 0` to `AgentInfo` and populate them in the introspection routes.

- **Effort:** Small
- **Risk:** Low (additive API change)

## Acceptance Criteria

- [ ] `AgentInfo` includes `retrievers` and `context_file_count` fields
- [ ] Introspection routes populate these fields
- [ ] Tests verify the fields appear in API responses
