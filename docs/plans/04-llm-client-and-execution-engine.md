---
title: "Phase 1.4: LLM Client & Execution Engine"
type: feat
status: completed
date: 2026-02-18
depends_on: [01, 02, 03]
blocks: [05, 06, 08]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.4: LLM Client & Execution Engine

## Goal

Build the LLM client wrapper (LiteLLM Router with failover) and the core execution engine — the function-calling loop that is the heart of agent invocations. After this phase, an agent can be invoked programmatically: send a message, the LLM reasons and calls tools, results are returned.

## Prerequisites

- Phase 01 (config, exceptions)
- Phase 02 (workspace, agent/tool models)
- Phase 03 (tool registry)

---

## Tasks

### 1. Data Models for Execution

**File:** `src/agent_gateway/engine/models.py`

Define all data structures used by the execution engine:

- `StopReason` enum: `COMPLETED`, `MAX_ITERATIONS`, `MAX_TOOL_CALLS`, `TIMEOUT`, `CANCELLED`, `ERROR`
- `ExecutionStatus` enum: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMEOUT`, `APPROVAL_PENDING`, `DENIED`
- `ToolCall` dataclass: name, arguments (dict), call_id
- `ToolResult` dataclass: success (bool), output (dict), duration_ms
- `UsageAccumulator` dataclass: tracks input_tokens, output_tokens, cost_usd, llm_calls, tool_calls, models_used across an execution
- `ExecutionOptions` dataclass: parsed from request options (async, timeout_ms, stream, callback_url, notify)
- `ExecutionResult` dataclass: output (dict|None), raw_text, stop_reason, usage, error, validation_errors

### 2. LLM Client

**File:** `src/agent_gateway/engine/llm.py`

Wrap LiteLLM Router for production use:

- Build `model_list` from gateway config + per-agent model overrides
- `RetryPolicy`: 2 retries for timeout, 3 for rate limit, 0 for auth/content errors
- `AllowedFailsPolicy`: 5 rate limit fails before cooldown, 3 timeout fails
- Cooldown: 60s
- Cost tracking via `litellm.completion_cost()`
- `acompletion()` for async calls
- `acompletion(stream=True)` for streaming
- Method: `async completion(messages, tools, model, temperature, max_tokens) -> LLMResponse`
- Method: `async stream_completion(messages, tools, model, ...) -> AsyncIterator[chunk]`

**Robustness details:**
- Both primary + fallback fail → raise `ExecutionError` with both error details
- Full message history sent to fallback model (context preserved)
- All failover events logged
- `litellm.set_verbose = False` in production
- `cache_responses = False` (agent responses are unique)

### 3. Execution Engine

**File:** `src/agent_gateway/engine/executor.py`

The core function-calling loop. This is the most critical code in the system.

**Loop structure:**
```
async def execute(agent, message, context, options) -> ExecutionResult:
    1. Build initial messages (system prompt + user message)
    2. Build tool declarations from resolved tools
    3. Initialize UsageAccumulator
    4. Wrap entire loop in asyncio.timeout(overall_timeout)

    5. while iteration < max_iterations:
        a. Check cancellation event
        b. Call LLM (try/except → StopReason.ERROR on failure)
        c. Record usage
        d. Extract tool_calls from response
        e. If no tool_calls → text response → break (COMPLETED)
        f. For each tool_call (parallel via TaskGroup + Semaphore):
           - Check max_tool_calls limit
           - Validate tool exists + agent has permission
           - Validate arguments against schema
           - Execute tool with per-tool timeout
           - Record in execution steps
           - Append tool_call + result to messages
        g. Loop back

    6. If loop exhausted → StopReason.MAX_ITERATIONS
    7. On TimeoutError → StopReason.TIMEOUT
    8. On CancelledError → StopReason.CANCELLED
```

**Error isolation rules:**
- Tool not found → return error as tool result: `{"error": "Unknown tool: 'foo'"}`
- Tool not permitted → return error as tool result
- Tool args invalid → return error as tool result with validation details
- Tool raises exception → catch, log, return error as tool result
- Tool times out → return error as tool result: `"Tool 'foo' timed out after 15s"`
- Tool result > 32KB → truncate with `"[truncated: result exceeded 32KB limit]"`
- LLM returns empty response → treat as completion with empty text
- LLM returns text + tool_calls → process tool_calls (text is intermediate)
- ALL of these keep the loop running — the LLM gets the error and can react

**Cancellation:**
- `ExecutionHandle` class with `asyncio.Event` for cooperative cancellation
- Checked at top of each iteration
- In-progress tool calls continue to completion (don't cancel mid-tool)
- In-progress LLM calls: `task.cancel()` via asyncio

**Parallel tool execution:**
- When LLM returns multiple tool_calls, execute with `asyncio.TaskGroup` + `Semaphore(5)`
- Each tool call still has its own timeout
- If any tool fails, others continue (error isolation per-tool)

### 4. Structured Output Validator

**File:** `src/agent_gateway/engine/output.py`

- If `output_schema` defined in agent config:
  1. Try native structured output (if LLM supports `response_format`)
  2. Else append schema instructions to system prompt
  3. Parse response as JSON
  4. Validate with `jsonschema.validate()` (add `jsonschema` to deps)
  5. If invalid: retry ONCE with correction prompt
  6. If retry fails: `result.output = None`, `result.raw_text = raw`, `result.validation_errors = [...]`
- Retry does NOT count against max_iterations
- Retry uses same model (not fallback)
- Invalid output_schema caught at workspace load time

### 5. Tool Context

**File:** Update `src/agent_gateway/engine/models.py`

```python
@dataclass
class ToolContext:
    """Context passed to tool handlers during execution."""
    execution_id: str
    agent_id: str
    caller_identity: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

The execution engine creates a `ToolContext` and passes it to tool executors.

---

## Tests

### Unit Tests

**`tests/test_engine/test_models.py`** — Data model construction, UsageAccumulator arithmetic

**`tests/test_engine/test_llm.py`** — LLM client with mocked LiteLLM (mock `acompletion`):
- Successful completion
- Tool call response parsing
- Cost tracking accumulation
- Failover to fallback model

**`tests/test_engine/test_executor.py`** — Core loop with mocked LLM client:
- Simple text response (no tools) → COMPLETED
- Single tool call → tool executed → second LLM call → COMPLETED
- Multiple tool calls in one response → parallel execution
- Multi-iteration loop (3 LLM calls with tools between)

**`tests/test_engine/test_executor_timeouts.py`**:
- Overall timeout fires → TIMEOUT
- Per-tool timeout fires → error returned to LLM, loop continues

**`tests/test_engine/test_executor_guardrails.py`**:
- Max iterations hit → MAX_ITERATIONS
- Max tool calls hit → MAX_TOOL_CALLS

**`tests/test_engine/test_executor_errors.py`**:
- Unknown tool name → error to LLM
- Tool permission denied → error to LLM
- Tool raises exception → error to LLM
- Tool returns oversized result → truncated
- LLM returns malformed tool args → error to LLM
- LLM returns empty response → COMPLETED with empty text
- LLM call fails → ERROR

**`tests/test_engine/test_executor_cancel.py`**:
- Cancel event set → CANCELLED
- Cancel during tool execution → current tool completes, then CANCELLED

**`tests/test_engine/test_executor_parallel.py`**:
- 3 parallel tool calls → all execute concurrently
- 1 of 3 fails → other 2 succeed, error returned for failing one

**`tests/test_engine/test_output.py`**:
- Valid JSON matching schema → output parsed
- Invalid JSON → retry → success
- Invalid JSON → retry → still invalid → output=None, validation_errors populated
- No schema → output=None, raw_text only

## Acceptance Criteria

- [x] LLM client wraps LiteLLM with failover and cost tracking
- [x] Execution loop handles all tool call patterns correctly
- [x] All 6 StopReasons tested and working
- [x] Tool errors never crash the loop
- [x] Parallel tool execution with bounded concurrency
- [x] Cancellation is cooperative and tested
- [x] Structured output validation with retry
- [x] Tool results truncated at 32KB
- [x] All tests pass
