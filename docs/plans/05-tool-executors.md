---
title: "Phase 1.5: Tool Executors (HTTP, Function, Script)"
type: feat
status: completed
date: 2026-02-18
depends_on: [01, 02, 03, 04]
blocks: [08]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.5: Tool Executors (HTTP, Function, Script)

## Goal

Implement the three tool executor types that actually run tools when the execution engine dispatches a tool call. After this phase, HTTP tools call external APIs, function tools run Python handlers, and script tools run subprocesses.

## Prerequisites

- Phase 04 (execution engine defines the interface tool executors must satisfy)

---

## Tasks

### 1. Tool Runner (Dispatcher)

**File:** `src/agent_gateway/tools/runner.py`

Dispatches tool calls to the correct executor based on tool type. Single entry point for the execution engine.

```python
async def execute_tool(
    tool: ResolvedTool,
    arguments: dict[str, Any],
    context: ToolContext,
) -> ToolResult:
    """Execute a tool call, dispatching to the correct executor."""
    if tool.source == "code":
        return await execute_code_tool(tool.code_tool, arguments, context)
    elif tool.file_tool is not None:
        match tool.file_tool.type:
            case "http":
                return await execute_http_tool(tool.file_tool, arguments, context)
            case "function":
                return await execute_function_tool(tool.file_tool, arguments, context)
            case "script":
                return await execute_script_tool(tool.file_tool, arguments, context)
            case _:
                return ToolResult(success=False, output={"error": f"Unknown tool type: {tool.file_tool.type}"})
    return ToolResult(success=False, output={"error": "Tool has no executor"})
```

### 2. HTTP Tool Executor

**File:** `src/agent_gateway/tools/http.py`

Calls external APIs defined in TOOL.md.

**Behavior:**
- Resolve `${VAR}` in URL, headers, and body from environment at execution time
- Unresolved `${VAR}` → `ToolResult(success=False, error="Missing env var: VAR")`
- Make HTTP request via shared `httpx.AsyncClient`
- Follow redirects (max 5)
- On 2xx: parse JSON response. If not JSON, return `{"text": "<body>"}`
- On 4xx: return raw body as tool result (LLM can interpret the error)
- On 5xx: retry once with 1s delay, then return error
- Response > 1MB: truncate with warning
- Per-tool timeout from `http.timeout_ms` (default 15s)
- Connection pooling: one `httpx.AsyncClient` shared across all HTTP tools, created on startup, closed on shutdown

**Environment variable resolution:**
```python
import os, re

def resolve_env_vars(template: str) -> str:
    """Replace ${VAR} with environment variable values."""
    def replacer(match):
        var = match.group(1)
        value = os.environ.get(var)
        if value is None:
            raise ConfigError(f"Missing environment variable: {var}")
        return value
    return re.sub(r'\$\{(\w+)\}', replacer, template)
```

### 3. Function Tool Executor

**File:** `src/agent_gateway/tools/function.py`

Runs Python functions — either `handler.py` from file-based tools or `@gw.tool` decorated functions.

**For code tools (`@gw.tool`):**
- Call the function directly with arguments
- If function is sync (not async): wrap in `asyncio.to_thread()`
- Pass `ToolContext` if function signature accepts a `context` parameter

**For file-based function tools (`handler.py`):**
- Import `handler.py` dynamically at workspace load time
- Look for `async def handle(params, context)` function
- If import fails: mark tool as broken, log error
- If `handle` not found: mark tool as broken
- If sync `def handle`: wrap in `asyncio.to_thread()`
- Call `handle(arguments, context)`

**Error handling:**
- Any exception → `ToolResult(success=False, output={"error": "Tool 'name' failed: TypeError: ..."})`
- Broken tools → `ToolResult(success=False, output={"error": "Tool 'name' is broken: import error details"})`

### 4. Script Tool Executor

**File:** `src/agent_gateway/tools/script.py`

Runs standalone scripts via subprocess.

**Behavior:**
- Run via `asyncio.create_subprocess_exec` (NOT `shell=True`)
- Working directory: tool's directory (`workspace/tools/{name}/`)
- Input: JSON-serialized arguments on stdin
- Output: read stdout, parse as JSON
- Stderr: capture and log (not returned to LLM)
- Timeout: from `script.timeout_ms` (default 30s)
- Kill on timeout: SIGTERM → wait 5s → SIGKILL
- Kill on cancellation: same SIGTERM/SIGKILL sequence
- Non-zero exit + valid JSON stdout: return the JSON
- Non-zero exit + invalid stdout: return error with exit code + stderr snippet
- Environment: inherit process env, but strip `AGENT_GATEWAY_*` internal vars

```python
async def execute_script_tool(tool, arguments, context):
    cmd = tool.script.command.split()
    env = _build_script_env()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(tool.path),
        env=env,
    )

    try:
        async with asyncio.timeout(tool.script.timeout_ms / 1000):
            stdout, stderr = await proc.communicate(
                input=json.dumps(arguments).encode()
            )
    except TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
        return ToolResult(success=False, output={"error": f"Script timed out after {tool.script.timeout_ms}ms"})

    if stderr:
        logger.debug("Script stderr for %s: %s", tool.name, stderr.decode()[:500])

    try:
        result = json.loads(stdout.decode())
        return ToolResult(success=True, output=result)
    except json.JSONDecodeError:
        return ToolResult(
            success=False,
            output={"error": f"Script returned invalid JSON. Exit code: {proc.returncode}"},
        )
```

---

## Tests

**`tests/test_tools/test_http.py`:**
- Mock httpx responses: 200 JSON, 200 non-JSON, 404, 500 (retry), timeout
- Env var resolution: valid, missing var
- Response truncation at 1MB
- Redirect following

**`tests/test_tools/test_function.py`:**
- Code tool: async function, sync function (to_thread)
- File tool: handler.py import, missing handle function, import error
- Context parameter injection
- Exception handling

**`tests/test_tools/test_script.py`:**
- Successful JSON output
- Non-zero exit with JSON
- Non-zero exit without JSON
- Timeout + kill
- Stderr captured
- Working directory set correctly

**`tests/test_tools/test_runner.py`:**
- Dispatch to correct executor by type
- Unknown type returns error

## Acceptance Criteria

- [x] Function tools run both code (@gw.tool) and file-based (handler.py) handlers
- [x] Sync and async handlers supported (sync wrapped in asyncio.to_thread)
- [x] ToolContext injection for functions that accept a context parameter
- [x] ToolRunner dispatches to correct executor based on tool source
- [x] All tests pass (184 total)
- N/A: HTTP and script executors removed — functions cover all use cases
