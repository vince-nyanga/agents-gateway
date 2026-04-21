---
status: pending
priority: p2
issue_id: "116"
tags: [code-review, testing, output-schema, hot-reload]
dependencies: []
---

# Missing integration test: set_output_schema survives hot-reload

## Problem Statement

`gateway.py` calls `_apply_pending_output_schemas(new_workspace)` in both the
initial startup path (line ~690) and the hot-reload path (line ~2254). The docstring
explicitly calls this out as required at BOTH sites. However, no integration test
exercises the hot-reload case — there is no test that:

1. Calls `gw.set_output_schema(agent_id, model)` before startup.
2. Triggers a workspace reload (via `POST /v1/reload` or direct `_reload_workspace()`).
3. Asserts that the agent still has `output_schema` and `_pydantic_output_model` set
   after the reload.

If the hot-reload site were accidentally removed, no test would catch it.

## Findings

- `src/agent_gateway/gateway.py` lines ~690 and ~2254 — both sites present.
- `docs/plans/2026-04-20-feat-agent-output-schema-plan.md` — no explicit hot-reload
  test required by the plan, but the code comment says "Must be called at BOTH sites".
- No file in `tests/` contains `reload` combined with `output_schema`.
- See todo 112 (missing reload test for LLM client) for the same pattern.

## Proposed Solutions

### Option A: Add integration test in test_output_schema.py (recommended)

Add a `TestHotReloadOutputSchema` class in
`tests/test_integration/test_output_schema.py`:

```python
@pytest.mark.asyncio
async def test_set_output_schema_survives_reload(self, output_schema_workspace, ...) -> None:
    gw = Gateway(workspace=str(output_schema_workspace), auth=False)
    gw.set_output_schema("plain", SummaryModel)
    async with gw:
        # Assert schema is set
        assert gw.workspace.agents["plain"]._pydantic_output_model is SummaryModel
        # Trigger reload
        await gw._do_reload()
        # Assert schema is still set after reload
        agent = gw.workspace.agents["plain"]
        assert agent._pydantic_output_model is SummaryModel
        assert agent.output_schema is not None
```

**Pros:** Directly exercises the code path.
**Cons:** Requires `_do_reload()` to be accessible or tested via `POST /v1/reload`.
**Effort:** Small.

### Option B: Add a unit test for _apply_pending_output_schemas

Test the private method directly with a mock workspace. Lower fidelity but simpler.

**Pros:** No need for the full reload machinery.
**Cons:** Does not catch integration-level failures.
**Effort:** Small.

## Recommended Action

Option A — real integration test on the reload path.

## Technical Details

- **Affected files:** `tests/test_integration/test_output_schema.py`, `src/agent_gateway/gateway.py`
- **Related todo:** 112 (LLM client missing reload test)

## Acceptance Criteria

- [ ] A test exists that calls `set_output_schema`, triggers a workspace reload, and
      asserts the schema is still present.
- [ ] Test passes with `uv run pytest tests/test_integration/test_output_schema.py -v`.

## Work Log

- 2026-04-21: Identified during output_schema feature code review.
