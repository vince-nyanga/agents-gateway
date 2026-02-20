---
status: pending
priority: p1
issue_id: "036"
tags: [code-review, performance, resource-management]
dependencies: []
---

# Unbounded Auto-Extraction Background Tasks

## Problem Statement
When `auto_extract` is enabled, every `chat()` call at `gateway.py:1514-1531` spawns a background `asyncio.Task` for LLM extraction with no throttling, deduplication, or debouncing. 100 rapid messages = 100 LLM calls, most producing redundant extractions from overlapping message windows.

## Findings
- **Performance reviewer**: CRITICAL — runaway LLM costs and task accumulation
- Each extraction involves an LLM API call (seconds of latency, billable tokens)
- `_background_tasks` set grows unboundedly during burst traffic
- No per-agent cooldown or deduplication

## Proposed Solutions

### Option A: Per-agent debounce/cooldown (Recommended)
```python
# In Gateway.__init__:
self._extraction_cooldowns: dict[str, float] = {}
_EXTRACTION_DEBOUNCE_SECONDS = 30.0

# In chat():
now = time.monotonic()
last = self._extraction_cooldowns.get(agent_id, 0.0)
if now - last >= _EXTRACTION_DEBOUNCE_SECONDS:
    self._extraction_cooldowns[agent_id] = now
    # ... create task
```
- **Effort**: Small (~10 LOC) | **Risk**: Low

## Acceptance Criteria
- [ ] Per-agent cooldown prevents rapid-fire extraction
- [ ] Configurable debounce interval
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
