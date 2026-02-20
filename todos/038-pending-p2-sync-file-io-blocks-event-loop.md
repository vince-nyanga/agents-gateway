---
status: pending
priority: p2
issue_id: "038"
tags: [code-review, performance, async]
dependencies: []
---

# Sync File I/O Blocks Event Loop in File Backend

## Problem Statement
`FileMemoryRepository` methods call `path.read_text()` and `path.write_text()` synchronously from async methods at `backends/file.py`. Under concurrent load, this blocks the event loop and degrades latency for all concurrent requests.

## Findings
- **Performance reviewer**: CRITICAL — event loop stalls cascade under moderate concurrency
- All async methods (`save`, `get`, `list_memories`, `search`, `delete`) call sync I/O

## Proposed Solutions

### Option A: Document as dev-only limitation (Recommended for v1)
Add docstring noting file backend is for low-concurrency/development use. Steer production to custom backends.
- **Effort**: Small | **Risk**: Low

### Option B: Wrap in asyncio.to_thread()
```python
records = await asyncio.to_thread(self._parse_file, agent_id)
```
- **Effort**: Medium | **Risk**: Low

## Acceptance Criteria
- [ ] File backend documented as dev/low-concurrency use
- [ ] Or sync I/O wrapped in asyncio.to_thread()
- [ ] Tests pass

## Work Log
- 2026-02-20: Created from code review findings
