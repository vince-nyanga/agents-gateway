"""agent-gateway chat — interactive multi-turn chat with an agent."""

from __future__ import annotations

import asyncio

import typer


def chat(
    agent_id: str = typer.Argument(help="Agent ID to chat with"),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Path to workspace directory"
    ),
) -> None:
    """Start an interactive chat session with an agent."""
    from agent_gateway.workspace.loader import load_workspace

    ws_path = workspace or "./workspace"
    state = load_workspace(ws_path)

    if state.errors:
        for err in state.errors:
            typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=1)

    if agent_id not in state.agents:
        typer.echo(f"Error: agent '{agent_id}' not found.", err=True)
        typer.echo(f"Available agents: {', '.join(sorted(state.agents.keys()))}", err=True)
        raise typer.Exit(code=1)

    asyncio.run(_chat_loop(ws_path, agent_id))


async def _chat_loop(workspace: str, agent_id: str) -> None:
    """Run an interactive chat session."""
    from agent_gateway.gateway import Gateway

    async with Gateway(workspace=workspace, auth=False) as gw:
        typer.echo(f"Chatting with '{agent_id}'. Type 'exit' or Ctrl+C to quit.\n")
        session_id: str | None = None
        loop = asyncio.get_event_loop()

        while True:
            try:
                message = (await loop.run_in_executor(None, lambda: input("you> "))).strip()  # noqa: ASYNC250
            except (EOFError, KeyboardInterrupt):
                typer.echo("\nBye!")
                break

            if not message:
                continue
            if message.lower() in ("exit", "quit"):
                typer.echo("Bye!")
                break

            try:
                session_id, result = await gw.chat(
                    agent_id=agent_id,
                    message=message,
                    session_id=session_id,
                )
                text = result.raw_text or "(no response)"
                typer.echo(f"\nagent> {text}\n")
            except Exception as e:
                typer.echo(f"\nError: {e}\n", err=True)
