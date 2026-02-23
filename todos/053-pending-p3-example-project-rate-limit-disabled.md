---
status: completed
priority: p3
issue_id: "053"
tags: [code-review, quality, rate-limiting, example-project]
dependencies: []
---

# Example project does not exercise rate limiting (feature is disabled)

## Problem Statement

Per CLAUDE.md: "After every feature or fix, the example project in `examples/test-project/` MUST be updated to exercise the change." The rate limiting entry in `examples/test-project/workspace/gateway.yaml` has `enabled: false` and all meaningful fields commented out. The feature is not exercised in the example project.

## Findings

- **File**: `examples/test-project/workspace/gateway.yaml:20-25`
```yaml
rate_limit:
  enabled: false
  # default_limit: "100/minute"
  # storage_uri: "redis://localhost:6379"
  # trust_forwarded_for: false
```
- The CLAUDE.md convention requires the example to exercise the feature, not just document its existence

## Proposed Solutions

### Option A: Enable rate limiting in the example project
Set `enabled: true` with a permissive limit (e.g. `"1000/minute"`) so it runs without impeding local `make dev` testing.
- **Effort**: Small
- **Risk**: None

### Option B: Add a comment explaining why it is disabled
If there is a deliberate reason (e.g. rate limiting breaks a test or demo flow), document it.
- **Effort**: Minimal
- **Risk**: None

## Recommended Action

_Leave blank — to be filled during triage._

## Technical Details

- **Affected files**: `examples/test-project/workspace/gateway.yaml`

## Acceptance Criteria

- [ ] `rate_limit.enabled: true` in the example project, OR a comment explains the exception to the CLAUDE.md rule

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-23 | Created from rate limiting implementation review | |

## Resources

- `examples/test-project/workspace/gateway.yaml`
- CLAUDE.md ("Example Project" section)
