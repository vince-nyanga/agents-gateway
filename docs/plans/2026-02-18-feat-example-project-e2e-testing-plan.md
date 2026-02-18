---
title: "feat: Example project E2E testing and polish"
type: feat
status: completed
date: 2026-02-18
---

# Example Project E2E Testing and Polish

## Overview

Turn the existing `examples/test-project/` into a polished, battle-tested example that serves two purposes: (1) an e2e test harness that exercises every implemented feature of agent-gateway with real Gemini LLM calls, and (2) a getting-started guide for new users. Fix any bugs discovered during e2e testing.

## Problem Statement / Motivation

The library has 317 unit/integration tests, but all LLM calls are mocked. No test has ever run against a real LLM provider. The example project exists but has never been validated end-to-end. There are likely bugs lurking in the full-stack path (workspace loading → prompt assembly → LLM call → tool execution → response formatting). Additionally, the example project has no README and isn't documented well enough to serve as a getting-started guide.

## Proposed Solution

1. **Fix the example project** — update model config to Gemini, fix known gaps (HTTP tool has no executor)
2. **Create e2e test infrastructure** — a `tests/test_e2e/` directory with real LLM calls, skippable in CI without API keys
3. **Write e2e tests** covering all implemented features: invoke, chat, sessions, introspection, CLI, error handling
4. **Polish the example** — add a README, inline comments, and clear setup instructions
5. **Fix bugs** discovered during testing

## Technical Considerations

### Model Configuration

- Change `gateway.yaml` default model from `gpt-4o-mini` to `gemini/gemini-2.0-flash` (LiteLLM format)
- Require `GEMINI_API_KEY` environment variable
- The DESIGN.md uses `google/gemini-2.5-flash` format — verify which LiteLLM prefix is correct

### HTTP Tool Executor Gap

The `http-example` tool is defined as `type: http` in its TOOL.md, but **no HTTP executor exists** in the codebase. The tool runner (`src/agent_gateway/tools/runner.py`) only handles `code` and `file` tools. Calling this tool at runtime raises `RuntimeError("Tool 'http-example' has no handler.py")`.

**Resolution:** Convert `http-example` to a file tool with a `handler.py` that makes the HTTP call using `httpx`. This keeps the tool functional without requiring the full HTTP executor (planned for a future phase).

### Non-Deterministic LLM Output

Real LLM calls produce non-deterministic text. E2e test assertions should focus on:

- HTTP status codes (200, 404, 422)
- Execution status (`completed`, `failed`)
- Structural properties (`usage.tool_calls >= 1`, non-empty `result.raw_text`)
- Presence of expected values in output (e.g., response contains "5" for a math question)

Temperature is already set to 0.1 in `gateway.yaml`, which helps reduce variance.

### Test Isolation

- E2e tests live in `tests/test_e2e/` with a `@pytest.mark.e2e` marker
- Skipped by default unless `AGENT_GATEWAY_E2E=1` env var is set
- Skip if `GEMINI_API_KEY` is not set (with clear skip message)
- Use `httpx.AsyncClient` with `ASGITransport` for API tests (same pattern as existing integration tests)
- Override persistence to `sqlite+aiosqlite:///:memory:` for test isolation
- Disable telemetry to keep test output clean

### CLI Testing

- `check`, `agents`, `skills` — use `CliRunner` from typer (no LLM needed)
- `invoke` — needs real LLM, test via subprocess pointing at example workspace
- `serve` — start as background subprocess, health-check poll, run requests, kill

## Acceptance Criteria

### Infrastructure

- [x] `tests/test_e2e/conftest.py` with gateway fixture using example workspace, Gemini model, in-memory SQLite
- [x] `@pytest.mark.e2e` marker registered in `pyproject.toml`
- [x] Tests skip gracefully when `GEMINI_API_KEY` is not set
- [x] `make test-e2e` target in Makefile

### Example Project Fixes

- [x] `gateway.yaml` updated to use `gemini/gemini-2.0-flash` as default model
- [x] `http-example` tool converted to file tool with `handler.py`
- [x] `.env.example` updated with clear instructions

### E2E Tests — Introspection & Health (no LLM)

- [x] `GET /v1/health` returns 200 with correct agent/skill/tool counts
- [x] `GET /v1/agents` lists `assistant` and `scheduled-reporter`
- [x] `GET /v1/agents/assistant` returns agent details with skills and tools
- [x] `GET /v1/skills` lists `math-workflow`
- [x] `GET /v1/tools` lists `echo`, `add-numbers`, and `http-example`
- [x] `GET /api/health` (custom route) returns 200

### E2E Tests — Error Handling (no LLM)

- [x] `POST /v1/agents/nonexistent/invoke` returns 404 with `agent_not_found`
- [x] `POST /v1/agents/assistant/invoke` with empty body returns 422
- [x] `POST /v1/agents/assistant/chat` with bad `session_id` returns 404

### E2E Tests — Invoke with Real LLM

- [x] Invoke `assistant` with a message that triggers `echo` tool — verify `usage.tool_calls >= 1`, status `completed`
- [x] Invoke `assistant` with a math question — verify `add_numbers` tool is called, result contains the answer
- [x] Invoke `assistant` with simple greeting (no tools) — verify text response
- [x] Invoke `scheduled-reporter` (no tools agent) — verify text response
- [ ] Invoke with `http-example` tool (after fix) — verify HTTP call succeeds

### E2E Tests — Chat & Sessions (Real LLM)

- [x] Chat new session — verify `session_id` returned, `turn_count == 1`
- [x] Chat multi-turn — second message with same `session_id`, verify `turn_count == 2`
- [x] Chat with tool use — verify tool is called within chat context
- [x] Chat SSE streaming — verify `text/event-stream` content type, parse events, verify `session`/`token`/`done` events
- [x] Session CRUD — `GET /v1/sessions`, `GET /v1/sessions/{id}`, `DELETE /v1/sessions/{id}`

### E2E Tests — CLI

- [x] `agent-gateway check --workspace examples/test-project/workspace` exits 0, lists agents/skills/tools
- [x] `agent-gateway agents --workspace examples/test-project/workspace` lists both agents
- [x] `agent-gateway skills --workspace examples/test-project/workspace` lists math-workflow
- [ ] `agent-gateway invoke assistant "What is 2+3?" --workspace examples/test-project/workspace` returns a result with "5"

### Example Project Polish

- [x] `examples/test-project/README.md` with setup instructions, prerequisites, and usage examples
- [ ] Inline comments in `app.py` explaining key concepts

## Success Metrics

- All e2e tests pass against real Gemini API
- Example project can be started from scratch by following the README
- Bugs discovered during e2e testing are fixed and covered by tests

## Dependencies & Risks

| Dependency/Risk | Impact | Mitigation |
|---|---|---|
| `GEMINI_API_KEY` required | Tests can't run without it | Skip with clear message; document in README |
| LLM non-determinism | Flaky tests | Assert on structure, not exact text; low temperature |
| httpbin.org availability | HTTP tool test flaky | Use a simple local handler instead of external service |
| HTTP tool executor not implemented | `http-example` fails at runtime | Convert to file tool with `handler.py` |
| Cost of real LLM calls | Small cost per test run | Use cheapest model (`gemini-2.0-flash`), keep prompts short |

## References & Research

### Internal References

- Example project: `examples/test-project/app.py`
- Gateway class: `src/agent_gateway/gateway.py`
- Tool runner: `src/agent_gateway/tools/runner.py`
- Integration test patterns: `tests/test_integration/conftest.py`
- Chat tests: `tests/test_chat/test_chat_endpoint.py`
- DESIGN.md model config: uses `google/gemini-2.5-flash` format

### Key Files to Create/Modify

- **Create:** `tests/test_e2e/conftest.py`
- **Create:** `tests/test_e2e/test_health_introspection.py`
- **Create:** `tests/test_e2e/test_invoke.py`
- **Create:** `tests/test_e2e/test_chat.py`
- **Create:** `tests/test_e2e/test_cli.py`
- **Create:** `tests/test_e2e/test_errors.py`
- **Create:** `examples/test-project/README.md`
- **Create:** `examples/test-project/workspace/tools/http-example/handler.py`
- **Modify:** `examples/test-project/workspace/gateway.yaml` (model → Gemini)
- **Modify:** `examples/test-project/workspace/tools/http-example/TOOL.md` (type → file)
- **Modify:** `Makefile` (add `test-e2e` target)
- **Modify:** `pyproject.toml` (register `e2e` marker)
