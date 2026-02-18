"""Agent Gateway CLI."""

import typer

from agent_gateway.cli.check import check
from agent_gateway.cli.init_cmd import init
from agent_gateway.cli.invoke import invoke
from agent_gateway.cli.list_cmd import agents, schedules, skills
from agent_gateway.cli.serve import serve

app = typer.Typer(
    name="agent-gateway",
    help="An opinionated FastAPI extension for building API-first AI agent services.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Show the agent-gateway version."""
    from agent_gateway import __version__

    typer.echo(f"agent-gateway {__version__}")


app.command()(init)
app.command()(serve)
app.command()(invoke)
app.command()(check)
app.command(name="agents")(agents)
app.command(name="skills")(skills)
app.command(name="schedules")(schedules)
