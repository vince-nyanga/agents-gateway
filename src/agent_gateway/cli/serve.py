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
    worker_only: bool = typer.Option(
        False, "--worker-only", help="Run queue workers only, no HTTP server"
    ),
) -> None:
    """Start the agent-gateway server."""
    from agent_gateway import Gateway
    from agent_gateway.config import GatewayConfig

    ws_path = workspace or "./workspace"

    if worker_only:
        _run_worker_only(ws_path)
        return

    import uvicorn

    # Load config to pick up port/host from gateway.yaml if not overridden
    config = GatewayConfig.load(Path(ws_path))
    effective_host = host if host != "0.0.0.0" else config.server.host
    effective_port = port if port != 8000 else config.server.port

    gw = Gateway(workspace=ws_path, reload=reload)
    gw._setup_logging()

    typer.echo(f"Starting agent-gateway on {effective_host}:{effective_port}")
    uvicorn.run(
        gw,
        host=effective_host,
        port=effective_port,
        reload=reload,
    )


def _run_worker_only(ws_path: str) -> None:
    """Run the gateway in worker-only mode — no HTTP server, just queue consumers."""
    import asyncio
    import signal

    import typer as _typer

    from agent_gateway import Gateway
    from agent_gateway.queue.backends.memory import MemoryQueue

    async def _main() -> None:
        gw = Gateway(workspace=ws_path)
        gw._setup_logging()

        await gw._startup()

        # Guard: memory backend cannot be shared across processes
        if isinstance(gw._queue, MemoryQueue):
            await gw._shutdown()
            _typer.echo(
                "Error: --worker-only requires a durable queue backend "
                "(redis or rabbitmq). Memory queue is single-process only.",
                err=True,
            )
            raise _typer.Exit(code=1)

        if gw._worker_pool is None:
            await gw._shutdown()
            _typer.echo(
                "Error: No queue backend configured. "
                "Set queue.backend in gateway.yaml or use a fluent API method.",
                err=True,
            )
            raise _typer.Exit(code=1)

        _typer.echo("Worker-only mode started. Press Ctrl+C to stop.")
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        await stop_event.wait()
        _typer.echo("Shutting down workers...")
        await gw._shutdown()

    asyncio.run(_main())
