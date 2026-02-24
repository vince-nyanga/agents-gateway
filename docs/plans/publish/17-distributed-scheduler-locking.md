---
title: "Distributed Scheduler Locking"
status: completed
priority: P2
category: Infrastructure
date: 2026-02-22
---

# Distributed Scheduler Locking

## Problem

If multiple gateway instances are running (horizontal scaling), each instance will fire the same scheduled job. No distributed lock prevents duplicate execution.

## Files to Change

- `src/agent_gateway/scheduler/engine.py`
- `src/agent_gateway/config.py`

## Plan

1. Add optional distributed lock backend (Redis or PostgreSQL advisory lock)
2. Before firing a scheduled job, acquire a named lock (`schedule:{schedule_id}:{fire_time}`)
3. If lock acquisition fails, skip the fire (another instance is handling it)
4. Release lock after job completes or times out
5. Make locking opt-in via config: `scheduler.distributed_lock: true`
6. When queue backend is Redis, reuse the Redis connection for locking
7. Document multi-instance deployment requirements
