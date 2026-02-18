"""agent-gateway init — scaffold a new project."""

from __future__ import annotations

from pathlib import Path

import typer


def init(
    project_name: str = typer.Argument(help="Name of the project to create"),
) -> None:
    """Scaffold a new agent-gateway project."""
    target = Path(project_name)

    if target.exists():
        typer.echo(f"Error: directory '{project_name}' already exists.", err=True)
        raise typer.Exit(code=1)

    # Create directory structure
    (target / "workspace" / "agents" / "assistant").mkdir(parents=True)
    (target / "workspace" / "skills").mkdir(parents=True)
    (target / "workspace" / "tools").mkdir(parents=True)

    # AGENT.md
    (target / "workspace" / "agents" / "assistant" / "AGENT.md").write_text(
        "# Assistant\n"
        "\n"
        "You are a helpful assistant.\n"
        "\n"
        "## Capabilities\n"
        "\n"
        "- Answer questions clearly and concisely\n"
        "- Use available tools when relevant\n"
    )

    # SOUL.md
    (target / "workspace" / "agents" / "assistant" / "SOUL.md").write_text(
        "# SOUL\n\nFriendly, concise, and helpful.\n"
    )

    # gateway.yaml
    (target / "workspace" / "gateway.yaml").write_text(
        "server:\n"
        "  port: 8000\n"
        "\n"
        "model:\n"
        '  default: "gpt-4o-mini"\n'
        "  temperature: 0.1\n"
        "\n"
        "auth:\n"
        "  enabled: false\n"
        "\n"
        "persistence:\n"
        "  enabled: true\n"
        "  backend: sqlite\n"
        f'  url: "sqlite+aiosqlite:///{project_name}.db"\n'
        "\n"
        "telemetry:\n"
        "  enabled: true\n"
        "  exporter: console\n"
    )

    # app.py
    (target / "app.py").write_text(
        '"""' + project_name + ' — an agent-gateway project."""\n'
        "\n"
        "from agent_gateway import Gateway\n"
        "\n"
        'gw = Gateway(workspace="./workspace")\n'
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    gw.run()\n"
    )

    # .env.example
    (target / ".env.example").write_text(
        "# LLM provider API key\n"
        "# OPENAI_API_KEY=sk-...\n"
        "# ANTHROPIC_API_KEY=sk-ant-...\n"
        "\n"
        "# Gateway overrides\n"
        "# AGENT_GATEWAY_SERVER__PORT=8000\n"
    )

    # .gitignore
    (target / ".gitignore").write_text("__pycache__/\n*.pyc\n.env\n*.db\n.venv/\ndist/\n")

    typer.echo(f"Created project '{project_name}'.")
    typer.echo()
    typer.echo("Next steps:")
    typer.echo(f"  cd {project_name}")
    typer.echo("  pip install agent-gateway")
    typer.echo("  python app.py")
