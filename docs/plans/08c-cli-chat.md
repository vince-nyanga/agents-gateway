---
title: "Phase 1.8c: Interactive CLI Chat Command"
type: feat
status: pending
date: 2026-02-18
depends_on: [08b]
blocks: []
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.8c: Interactive CLI Chat Command

## Goal

Add `agent-gateway chat <agent_id>` command that starts an interactive REPL session for multi-turn conversations with an agent directly from the terminal. Complements the HTTP chat endpoint from Phase 08b.

## Prerequisites

- Phase 08b (Multi-Turn Chat Endpoint) complete

---

## Design

### Two Modes

**Interactive REPL mode** (default — no message argument):

```
$ agent-gateway chat assistant
Chat session started (sess_a1b2c3d4e5f6)
Agent: assistant | Type 'exit' or Ctrl+C to quit.

You: What is 2 + 3?
Assistant: 2 + 3 = 5

You: Now multiply that by 10
Assistant: 5 × 10 = 50

You: exit
Session ended. 3 turns.
```

**Single-shot mode** (message provided as argument):

```
$ agent-gateway chat assistant "What is 2+3?"
Assistant: 2 + 3 = 5
```

### CLI Signature

```
agent-gateway chat <agent_id> [message] [--workspace PATH] [--json] [--session SESSION_ID]
```

| Argument / Option | Type | Default | Description |
|---|---|---|---|
| `agent_id` | str (required) | — | Agent to chat with |
| `message` | str (optional) | None | If provided, single-shot mode |
| `--workspace / -w` | str | `./workspace` | Path to workspace directory |
| `--json` | bool | False | Output raw JSON instead of human-friendly text |
| `--session` | str | None | Resume an existing session ID (single-shot only) |

---

## Tasks

### 1. Chat Command Implementation

**File:** `src/agent_gateway/cli/chat.py`

- [ ] `chat()` function with Typer argument/option declarations
- [ ] Interactive REPL mode via `while True` loop with `typer.prompt("You")`
- [ ] Single-shot mode when `message` argument is provided
- [ ] Call `gw.chat(agent_id, message, session_id=session_id)` per turn
- [ ] Reuse returned `session_id` across turns in interactive mode
- [ ] Handle Ctrl+C (KeyboardInterrupt) gracefully — print summary, exit cleanly
- [ ] Handle EOF (Ctrl+D / EOFError) same as exit
- [ ] Print session_id on start so user knows which session they're in
- [ ] Print turn count summary on exit
- [ ] `--json` flag: output `result.to_dict()` as JSON per turn
- [ ] `--session` flag: pass existing session_id for single-shot continuation
- [ ] Gateway created with `auth=False` (CLI is local)
- [ ] Validate agent exists before entering REPL (fail fast)

### 2. Register Command

**File:** `src/agent_gateway/cli/main.py`

- [ ] Import chat from `agent_gateway.cli.chat`
- [ ] Register via `app.command()(chat)`

### 3. Tests

**File:** `tests/test_cli/test_chat.py`

- [ ] Test single-shot mode with mock LLM returns expected output
- [ ] Test `--json` flag outputs valid JSON
- [ ] Test agent-not-found prints error and exits with code 1
- [ ] Test chat command is registered and shows in `--help`

---

## Acceptance Criteria

- [ ] `agent-gateway chat assistant` starts interactive REPL
- [ ] `agent-gateway chat assistant "hello"` sends one message and exits
- [ ] Session persists across turns in interactive mode
- [ ] Ctrl+C exits gracefully with session summary
- [ ] `--json` flag outputs structured JSON
- [ ] Invalid agent prints error and exits with code 1
- [ ] All tests pass
