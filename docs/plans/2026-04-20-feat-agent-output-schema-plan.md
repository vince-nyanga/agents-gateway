---
title: "feat: Add output_schema to agent frontmatter for structured JSON output"
type: feat
status: proposed
date: 2026-04-20
---

# feat: Add output_schema to agent frontmatter for structured JSON output

## Overview

Let agents declare a JSON Schema for their **structured output** directly in AGENT.md frontmatter. When an agent with an `output_schema` is invoked (HTTP or programmatic), the execution engine instructs the LLM to emit JSON matching that schema, parses the result, and validates it — without the caller having to pass an `options.output_schema` every time.

This completes the symmetry started by the existing `input_schema` feature (`docs/plans/2026-02-20-feat-agent-input-schema-plan.md`): agents can now declare both their input contract and their output contract as first-class properties of their definition, not per-request options.

## Problem Statement / Motivation

Today, structured output is a **per-invocation** concern — the caller must pass `options.output_schema` on every HTTP `invoke` call or via the `ExecutionOptions` argument when calling `gw.invoke()` programmatically. This has several problems:

1. **Duplication / drift** — Callers have to know and repeat the schema on every invocation. In delegation (`delegate_to_agent`) the schema is lost because the delegating tool cannot know what structure the sub-agent returns.
2. **Not discoverable** — `GET /v1/agents/{id}` does not tell you what shape the agent outputs. Humans and other agents cannot discover the contract.
3. **Scheduled runs** — Agents triggered by cron schedules have no way to produce structured output because no caller is setting `options.output_schema`.
4. **Agent-to-agent contracts** — The input-schema plan explicitly calls this out as a follow-up: "Output schema on AgentDefinition — the same pattern should be applied to `output_schema`."

The existing `engine/output.py` validation machinery is complete and production-tested — all that is missing is the wiring from frontmatter → `AgentDefinition` → `ExecutionOptions.output_schema`.

## Proposed Solution

Add an `output_schema` field to `AgentDefinition`, parsed from AGENT.md YAML frontmatter as an **inline JSON Schema dict**. When present, the execution engine treats it as a default `ExecutionOptions.output_schema` unless the caller explicitly overrides it. Validation reuses the existing `engine/output.py` pipeline (append `SCHEMA_INSTRUCTION` to the system prompt, parse JSON from LLM response, validate with `jsonschema`, return in `ExecutionResult.output`).

### Example: AGENT.md with output_schema

```yaml
---
description: "Extracts structured candidate data from resume text"
skills:
  - resume-parsing
output_schema:
  type: object
  properties:
    full_name:
      type: string
    email:
      type: string
      format: email
    years_experience:
      type: integer
      minimum: 0
    skills:
      type: array
      items:
        type: string
  required: [full_name, years_experience]
  additionalProperties: false
---

# Resume Parser

You are a resume parser. Extract structured candidate data from the provided resume text.
```

### Example: Discovery

```json
GET /v1/agents/resume-parser
{
  "id": "resume-parser",
  "description": "Extracts structured candidate data from resume text",
  "input_schema": null,
  "output_schema": {
    "type": "object",
    "properties": { "...": "..." },
    "required": ["full_name", "years_experience"]
  },
  "execution_mode": "sync"
}
```

### Example: Invocation returns structured output

```json
POST /v1/agents/resume-parser/invoke
{ "message": "Parse this resume:\n...", "options": {} }

200 OK
{
  "output": {
    "full_name": "Alex Rivera",
    "email": "alex@example.com",
    "years_experience": 8,
    "skills": ["python", "fastapi", "postgres"]
  },
  "raw_text": "{...}",
  "validation_errors": null
}
```

## Technical Approach

### Design Decisions

1. **Inline JSON Schema only (no `output_schema_file: path.json`)** — We accept only an inline dict in frontmatter. This mirrors the existing `input_schema` feature, which is also inline. Justification:
   - Consistency with `input_schema`, `setup_schema` — no special-casing.
   - One source of truth per agent; no hidden file dependency that can go missing.
   - YAML supports multi-line structured data well; agent schemas are typically 10–40 lines.
   - Keeps the loader simple — no path resolution, no symlink handling, no workspace-escape checks.
   - If teams want to share schemas, they can use YAML anchors (`<<: *common-output`) in a single AGENT.md or a future `workspace/schemas/` helper (out of scope here).
   - Pydantic `BaseModel` registration remains available via a programmatic API on `Gateway`, again mirroring `input_schema`.

2. **Load-time schema validation** — Use `jsonschema.Draft202012Validator.check_schema()` (the same helper already used by `_parse_input_schema` and `_parse_setup_schema` in `workspace/agent.py`). On failure, log a warning and set `output_schema = None` — do NOT crash the loader. This matches every other frontmatter parse helper.

3. **Frontmatter schema beats nothing, caller options beat frontmatter** — Precedence:

   ```
   options.output_schema (per-call)   ← wins
          ↓ (only if None)
   agent.output_schema (frontmatter)  ← default
          ↓ (only if None)
   None — agent returns free text
   ```
   The caller can always override (e.g. to request a narrower schema for a specific use-case). Code-registered Pydantic models (via `gw.set_output_schema()`) are stored on the agent and behave identically to frontmatter.

4. **LLM support strategy — system-prompt instruction, not native `response_format`** — The existing `engine/output.py` already appends a `SCHEMA_INSTRUCTION` to the system prompt. We keep that path:
   - Works with every LiteLLM provider (Anthropic, Gemini, Bedrock, local Ollama, Azure) — no provider-specific native JSON-mode probing required.
   - Existing correction-retry loop handles malformed output.
   - No new code paths; we only change *where the schema comes from*.
   - **Future work (out of scope)**: opportunistically pass `response_format={"type": "json_schema", "json_schema": {...}}` when the resolved model is known to support it (GPT-4o, Gemini 1.5+). The `LLMClient.completion()` already accepts a `response_format` kwarg but no caller uses it today. This is a separate optimization.

5. **Validation + correction is already implemented** — `Executor._build_completion_result()` and the retry path at `executor.py:780-820` already parse + validate + optionally retry with a correction prompt. No new engine code is required; we only make sure `options.output_schema` defaults to `agent.output_schema`.

6. **What happens if the LLM produces unparseable output** — Current behavior is preserved: one correction retry, then if still invalid, return `ExecutionResult(raw_text=..., validation_errors=[...], output=None, stop_reason=COMPLETED)`. HTTP response returns 200 with `validation_errors` populated (not 422 — the execution ran successfully, only the validation failed). Callers can inspect `validation_errors` to decide whether to retry.

7. **Chat is NOT affected** — Chat is conversational and free-text. Even if an agent has an `output_schema`, chat endpoints will NOT force JSON output, for the same reasons `input_schema` is skipped in chat. The engine only applies `output_schema` on the `invoke` and scheduled-execution paths (i.e. wherever an `ExecutionOptions` is constructed and passed to `Executor.execute`). Chat streaming uses `stream_chat_execution`, which builds its own `ExecutionOptions()` without `output_schema`.

8. **Delegation inherits the sub-agent's schema** — The `delegate_to_agent` tool calls `gw.invoke(sub_agent_id, ...)` internally. Because the sub-agent's `AgentDefinition.output_schema` is now consulted automatically, delegated calls will return structured output without any delegator-side plumbing.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Definition & Parsing                          │
│  AgentDefinition.output_schema (workspace/agent.py)     │
│  Parsed from AGENT.md YAML frontmatter                  │
│  Or registered via gw.set_output_schema() (Pydantic)    │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Resolution at invoke time                     │
│  gateway.invoke() + api/routes/invoke.py                │
│  effective_schema = options.output_schema               │
│                     or agent.output_schema              │
│                     or agent._pydantic_output_model     │
│  Build ExecutionOptions(output_schema=effective_schema) │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Execution (reuses existing engine/output.py)  │
│  executor._execute_loop appends SCHEMA_INSTRUCTION      │
│  _build_completion_result parses + validates            │
│  Correction retry happens inside executor               │
├─────────────────────────────────────────────────────────┤
│  Layer 4: Exposure                                      │
│  AgentInfo.output_schema                                │
│  GET /v1/agents, GET /v1/agents/{id}                    │
└─────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Data Model & Parsing

**Files modified:**
- `src/agent_gateway/workspace/agent.py`

**Tasks:**

1. Add `output_schema: dict[str, Any] | None = None` to `AgentDefinition` (next to `input_schema` at `agent.py:70`).
   ```python
   input_schema: dict[str, Any] | None = None
   output_schema: dict[str, Any] | None = None
   ```

2. Add a private `_pydantic_output_model: type[BaseModel] | None = None` field on `AgentDefinition` (dataclass `field(default=None, repr=False)`) to hold a programmatically-registered Pydantic class. This enables stronger Pydantic-based validation at invoke time while keeping the public JSON Schema available for introspection.

3. Add `_parse_output_schema()` in `workspace/agent.py` — identical in shape to `_parse_input_schema()` at `agent.py:332`:
   ```python
   def _parse_output_schema(raw: Any, agent_dir: Path) -> dict[str, Any] | None:
       if raw is None:
           return None
       if not isinstance(raw, dict):
           logger.warning("Invalid output_schema (not a dict) in %s, ignoring", agent_dir)
           return None
       import jsonschema
       try:
           jsonschema.Draft202012Validator.check_schema(raw)
       except jsonschema.SchemaError as e:
           logger.warning(
               "Invalid JSON Schema in output_schema for %s: %s, ignoring",
               agent_dir, e.message,
           )
           return None
       return raw
   ```

4. Wire it into `AgentDefinition.load()` next to the existing `input_schema` parse (around `agent.py:167`):
   ```python
   output_schema = _parse_output_schema(agent_meta.get("output_schema"), agent_dir)
   ```
   and pass it to the constructor at `agent.py:220-243`.

**Success criteria:**
- Agents with valid `output_schema` in AGENT.md load cleanly and `agent.output_schema` contains the dict.
- Agents with invalid `output_schema` (not a dict, or not a valid JSON Schema) load with `output_schema = None` and a warning is emitted.
- Agents without `output_schema` continue to load unchanged.

### Phase 2: Resolution at Invoke Entry Points

**Files modified:**
- `src/agent_gateway/api/routes/invoke.py`
- `src/agent_gateway/gateway.py` (`invoke()` method at ~line 2614)
- `src/agent_gateway/scheduler/` (scheduled-execution caller — discover during implementation; search for where `ExecutionOptions` is built for cron fires)

**Tasks:**

1. **HTTP invoke route** (`api/routes/invoke.py:~156`) — merge the agent's schema into `ExecutionOptions`:
   ```python
   effective_output_schema = body.options.output_schema or agent.output_schema
   options = ExecutionOptions(
       timeout_ms=body.options.timeout_ms,
       stream=body.options.stream,
       output_schema=effective_output_schema,
   )
   ```

2. **Programmatic `gw.invoke()`** (`gateway.py:2614`) — same merge. If `options` is None, synthesize one that picks up `agent.output_schema`. If `agent._pydantic_output_model` is set, prefer the model class (it carries more validation information):
   ```python
   if options is None:
       options = ExecutionOptions()
   if options.output_schema is None:
       options.output_schema = (
           agent._pydantic_output_model or agent.output_schema
       )
   ```
   Because `ExecutionOptions.output_schema` is already typed `dict[str, Any] | type[BaseModel] | None`, both variants are accepted.

3. **Scheduler** — wherever the scheduler creates `ExecutionOptions` for a cron fire, apply the same default. This keeps scheduled runs emitting structured output.

4. **Do NOT touch the chat route** — `api/routes/chat.py` builds its own `ExecutionOptions()` in `stream_chat_execution` and must continue to pass `output_schema=None`. Add an inline comment referencing this plan so future contributors don't "fix" it.

**Success criteria:**
- Calling `POST /v1/agents/resume-parser/invoke` with no `options.output_schema` produces a response whose `output` matches the frontmatter schema.
- Calling `gw.invoke("resume-parser", "...")` with no `options` produces the same result.
- Calling `POST /v1/agents/resume-parser/chat` never forces structured output; the stream is free text.
- Calling invoke with `options.output_schema` set still wins (override works).

### Phase 3: Introspection API

**Files modified:**
- `src/agent_gateway/api/models.py` (`AgentInfo`)
- `src/agent_gateway/api/routes/introspection.py`

**Tasks:**

1. Add `output_schema: dict[str, Any] | None = None` to `AgentInfo` (next to the existing `input_schema` field). The `AgentInfo` model already declares `input_schema`, so the change is one line + one populated kwarg.

2. In `introspection.py`, populate `output_schema=agent.output_schema` alongside `input_schema=agent.input_schema` in both `list_agents()` and `get_agent()`.

3. If a Pydantic model was registered via `gw.set_output_schema()`, the agent's `output_schema` field still holds its resolved JSON Schema — so introspection "just works" without special-casing.

**Success criteria:**
- `GET /v1/agents` includes `output_schema` for every agent (null if unset).
- `GET /v1/agents/{id}` includes `output_schema`.

### Phase 4: Programmatic Pydantic Registration API

**Files modified:**
- `src/agent_gateway/gateway.py`

**Tasks:**

1. Add `gw.set_output_schema(agent_id, schema)` — mirror `gw.set_input_schema()` if it exists, otherwise introduce the pair following the same pending-registration pattern used elsewhere in `Gateway`:
   ```python
   def set_output_schema(
       self,
       agent_id: str,
       schema: dict[str, Any] | type[BaseModel],
   ) -> None:
       """Set an output schema for an agent programmatically.

       Accepts either a JSON Schema dict or a Pydantic BaseModel class.
       Pydantic classes give stronger validation at completion time.
       Must be called before startup; takes effect after workspace load.
       """
       self._pending_output_schemas[agent_id] = schema
   ```

2. Add `self._pending_output_schemas: dict[str, dict[str, Any] | type[BaseModel]] = {}` in `Gateway.__init__`.

3. In the post-workspace-load pass (search for `_pending_input_schemas` application, apply the same pattern next to it — expected location is the post-startup "apply code registrations" block):
   ```python
   for aid, schema in self._pending_output_schemas.items():
       agent = workspace.agents.get(aid)
       if agent is None:
           logger.warning("set_output_schema: agent %r not found", aid)
           continue
       from agent_gateway.engine.output import resolve_schema
       json_schema, model_cls = resolve_schema(schema)
       agent.output_schema = json_schema
       agent._pydantic_output_model = model_cls
   ```

4. Code registration **overrides** frontmatter (code wins over config — consistent with code tools overriding file tools per CLAUDE.md conventions).

**Success criteria:**
- `gw.set_output_schema("resume-parser", ResumeModel)` before `gw.managed()` / startup registers the schema.
- After startup, `agent.output_schema` holds the Pydantic-derived JSON Schema and invocation returns a validated model.
- Registering a schema for an unknown agent ID warns but does not crash.

## Testing Strategy

**New test files:**
- `tests/workspace/test_agent_output_schema.py` — parsing + load-time validation
- `tests/engine/test_output_schema_from_agent.py` — end-to-end invocation with frontmatter schema
- `tests/api/test_invoke_output_schema.py` — HTTP layer tests

**Unit tests (parsing):**
- Valid output_schema in AGENT.md → `agent.output_schema` is the dict.
- `output_schema` not a dict → warning + `output_schema is None`.
- `output_schema` with invalid JSON Schema (e.g. `type: "bogus"`) → warning + `None`.
- No `output_schema` key → `None`.

**Unit tests (introspection):**
- `AgentInfo` returned by `get_agent()` / `list_agents()` includes `output_schema`.

**Integration tests (engine — mock LLM):**
- Agent with `output_schema` → LLM receives system prompt containing `## Required Output Format`.
- LLM returns valid JSON → `ExecutionResult.output` is the parsed dict.
- LLM returns invalid JSON → correction retry fires; if second attempt valid, `output` populated.
- LLM returns invalid JSON twice → `ExecutionResult.validation_errors` populated and `output is None`.
- Caller's `options.output_schema` overrides `agent.output_schema`.
- Chat streaming does NOT inject schema instruction into the system prompt even when `agent.output_schema` is set.

**Integration tests (Pydantic API):**
- `gw.set_output_schema("agent", MyModel)` → `agent.output_schema` is the model's JSON Schema; `ExecutionResult.output` is the parsed dict (the Pydantic model validates internally).
- Setting a schema for a missing agent warns but does not raise.

**HTTP tests:**
- `POST /v1/agents/{id}/invoke` with no `options` → response `output` matches frontmatter schema.
- `POST /v1/agents/{id}/invoke` with `options.output_schema` override → response uses the override.
- `GET /v1/agents/{id}` → `output_schema` field present.

## Example Project Updates

**Target agent:** `examples/test-project/workspace/agents/data-analyst/AGENT.md`

Add an `output_schema` that constrains the analyst to return a report summary:

```yaml
output_schema:
  type: object
  properties:
    summary:
      type: string
      description: One-paragraph narrative summary
    key_metrics:
      type: array
      items:
        type: object
        properties:
          name: { type: string }
          value: { type: number }
          unit: { type: string }
        required: [name, value]
    risks:
      type: array
      items: { type: string }
  required: [summary, key_metrics]
  additionalProperties: false
```

Verify via `make dev`:
```bash
curl -X POST http://localhost:8000/v1/agents/data-analyst/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Analyze Q1 sales: 120k in Jan, 140k Feb, 165k Mar"}'
```
Response's `output` field should be a parsed JSON object with `summary`, `key_metrics`, `risks`.

Also add a Pydantic demo in `examples/test-project/app.py` to exercise `gw.set_output_schema()` against a second agent (for example, decorate a `ResumeModel` with `pydantic.BaseModel` and wire it to a new `resume-parser` agent).

## Documentation Updates

1. **`docs/guides/structured-output.md`** — Currently documents per-call `options.output_schema`. Add a new section "Declaring schemas in AGENT.md" showing the frontmatter form and explaining precedence (caller options > frontmatter > none).

2. **`docs/guides/agents.md`** — Add `output_schema` to the frontmatter reference table next to `input_schema`, with a short example.

3. **`docs/api-reference/gateway.md`** — Document `gw.set_output_schema(agent_id, schema)` next to `gw.set_input_schema()`.

4. **`docs/llms.txt`** — Add a one-line entry for the new feature under the "Agent definitions" section so AI consumers discover it.

5. **`docs/changelog.md`** — Add an entry under the next unreleased version.

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing agents break because their free-text output no longer parses as JSON | None | N/A | Feature is opt-in. No `output_schema` = no behavior change. |
| Schema in AGENT.md is itself invalid | Medium | Low | Validated via `jsonschema.Draft202012Validator.check_schema()` at load time with a warning. |
| LLM ignores schema instruction and returns prose | Medium | Medium | Existing correction-retry loop in `engine/output.py` handles this; tests cover the double-failure case. |
| Caller's per-call `options.output_schema` is silently overridden | None | N/A | Merge precedence gives the caller priority; tested explicitly. |
| Chat accidentally forces JSON | Low | High (bad UX) | Chat uses its own `ExecutionOptions()`; inline comment warns against "fixing" the asymmetry; test asserts chat stream is free text even when `output_schema` is set. |
| Pydantic registered for missing agent leaks memory | Low | Low | Warning log; no retry; pending dict is cleared on reload. |

## Verification Checklist

```bash
uv run ruff format src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -m "not e2e" -x -q
```

Plus manual verification via the example project:
```bash
make dev
curl -X POST http://localhost:8000/v1/agents/data-analyst/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "..."}'
# Response should contain a validated `output` object.
```

## References

- Agent definition: `src/agent_gateway/workspace/agent.py:50-243`
- `_parse_input_schema` (template): `src/agent_gateway/workspace/agent.py:332-359`
- Existing output validation pipeline: `src/agent_gateway/engine/output.py`
- Executor schema injection: `src/agent_gateway/engine/executor.py:152-170`, `780-846`
- `AgentInfo`: `src/agent_gateway/api/models.py` (has `input_schema` already)
- HTTP invoke route (merge point): `src/agent_gateway/api/routes/invoke.py:~156`
- Programmatic invoke (merge point): `src/agent_gateway/gateway.py:2614-2665`
- Input-schema prior art (pattern we follow): `docs/plans/2026-02-20-feat-agent-input-schema-plan.md`
- Exception base: `src/agent_gateway/exceptions.py` (no new exception needed — validation errors are already returned on `ExecutionResult.validation_errors`)
