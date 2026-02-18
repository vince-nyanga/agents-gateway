"""Test project for agent-gateway development."""

from agent_gateway import Gateway

gw = Gateway(workspace="./workspace", auth=False, title="Test Project")


@gw.tool()
async def echo(message: str) -> dict:
    """Echo a message back - for testing the tool pipeline."""
    return {"echo": message}


@gw.tool()
async def add_numbers(a: float, b: float) -> dict:
    """Add two numbers - for testing structured params."""
    return {"result": a + b}


# --- Lifecycle hooks ---


@gw.on("agent.invoke.before")
async def log_invoke(agent_id, message, execution_id, **kw):
    print(f"[hook] invoke start: agent={agent_id} exec={execution_id}")


@gw.on("agent.invoke.after")
async def log_result(agent_id, execution_id, result, **kw):
    print(f"[hook] invoke done: agent={agent_id} exec={execution_id} stop={result.stop_reason.value}")


@gw.on("tool.execute.before")
async def log_tool(tool_name, agent_id, **kw):
    print(f"[hook] tool start: {tool_name} (agent={agent_id})")


@gw.on("tool.execute.after")
async def log_tool_done(tool_name, duration_ms, success, **kw):
    print(f"[hook] tool done: {tool_name} {duration_ms}ms ok={success}")


@gw.get("/api/health")
async def health():
    return {"status": "ok", "project": "test-project"}


if __name__ == "__main__":
    gw.run(port=8000)
