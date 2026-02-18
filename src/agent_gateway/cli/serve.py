"""agent-gateway serve — start the gateway server."""

from __future__ import annotations

from pathlib import Path

import typer


def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind address"),
    port: int = typer.Option(8000, "--port", "-p", help="Port number"),
    reload: bool = typer.Option(False, "--reload", help="Enable hot-reload"),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Path to workspace directory"
    ),
) -> None:
    """Start the agent-gateway server."""
    import uvicorn

    from agent_gateway import Gateway
    from agent_gateway.config import GatewayConfig

    ws_path = workspace or "./workspace"

    # Load config to pick up port/host from gateway.yaml if not overridden
    config = GatewayConfig.load(Path(ws_path))
    effective_host = host if host != "0.0.0.0" else config.server.host
    effective_port = port if port != 8000 else config.server.port

    gw = Gateway(workspace=ws_path, reload=reload)

    typer.echo(f"Starting agent-gateway on {effective_host}:{effective_port}")
    uvicorn.run(
        gw,
        host=effective_host,
        port=effective_port,
        reload=reload,
    )
