"""agent-gateway agents/skills/schedules — list discovered resources."""

from __future__ import annotations

import typer

from agent_gateway.workspace.loader import WorkspaceState


def _load_state(workspace: str | None) -> WorkspaceState:
    from agent_gateway.workspace.loader import load_workspace

    ws_path = workspace or "./workspace"
    state = load_workspace(ws_path)

    if state.errors:
        for err in state.errors:
            typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=1)

    return state


def agents(
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Path to workspace directory"
    ),
) -> None:
    """List all discovered agents."""
    state = _load_state(workspace)

    if not state.agents:
        typer.echo("No agents found.")
        return

    # Header
    typer.echo(f"{'ID':<25} {'Skills':<8} {'Tools':<8} {'Model':<25}")
    typer.echo("-" * 66)

    for agent_id, agent in sorted(state.agents.items()):
        model = agent.model.name or "(default)"
        typer.echo(f"{agent_id:<25} {len(agent.skills):<8} {len(agent.tools):<8} {model:<25}")


def skills(
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Path to workspace directory"
    ),
) -> None:
    """List all discovered skills."""
    state = _load_state(workspace)

    if not state.skills:
        typer.echo("No skills found.")
        return

    typer.echo(f"{'ID':<25} {'Tools':<30} {'Description':<40}")
    typer.echo("-" * 95)

    for skill_id, skill in sorted(state.skills.items()):
        tools_str = ", ".join(skill.tools) if skill.tools else "(none)"
        desc = skill.description[:40] if skill.description else ""
        typer.echo(f"{skill_id:<25} {tools_str:<30} {desc:<40}")


def schedules(
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Path to workspace directory"
    ),
) -> None:
    """List all discovered schedules."""
    state = _load_state(workspace)

    if not state.schedules:
        typer.echo("No schedules found.")
        return

    typer.echo(f"{'Name':<30} {'Agent':<20} {'Cron':<20} {'Enabled':<8} {'Timezone':<15}")
    typer.echo("-" * 93)

    for sched in state.schedules:
        # Find which agent owns this schedule
        agent_id = "(unknown)"
        for aid, agent in state.agents.items():
            if sched in agent.schedules:
                agent_id = aid
                break

        enabled = "yes" if sched.enabled else "no"
        tz = sched.timezone or "UTC"
        typer.echo(f"{sched.name:<30} {agent_id:<20} {sched.cron:<20} {enabled:<8} {tz:<15}")
