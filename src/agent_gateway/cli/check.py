"""agent-gateway check — validate a workspace."""

from __future__ import annotations

import typer


def check(
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Path to workspace directory"
    ),
) -> None:
    """Validate a workspace and report any issues."""
    from agent_gateway.workspace.loader import load_workspace

    ws_path = workspace or "./workspace"
    state = load_workspace(ws_path)

    # Print summary
    agent_count = len(state.agents)
    skill_count = len(state.skills)
    tool_count = len(state.tools)
    schedule_count = len(state.schedules)

    typer.echo(f"Workspace: {state.path}")
    typer.echo()

    # Agents
    typer.echo(f"Agents ({agent_count}):")
    for agent_id, agent in sorted(state.agents.items()):
        skills_info = f", skills: {len(agent.skills)}" if agent.skills else ""
        tools_info = f", tools: {len(agent.tools)}" if agent.tools else ""
        typer.echo(f"  [ok] {agent_id}{skills_info}{tools_info}")

    # Skills
    if state.skills:
        typer.echo(f"\nSkills ({skill_count}):")
        for skill_id, skill in sorted(state.skills.items()):
            tools_info = f" (tools: {', '.join(skill.tools)})" if skill.tools else ""
            typer.echo(f"  [ok] {skill_id}{tools_info}")

    # Tools
    if state.tools:
        typer.echo(f"\nTools ({tool_count}):")
        for tool_id, tool in sorted(state.tools.items()):
            kind = "function" if tool.handler_path else "http"
            typer.echo(f"  [ok] {tool_id} ({kind})")

    # Schedules
    if state.schedules:
        typer.echo(f"\nSchedules ({schedule_count}):")
        for sched in state.schedules:
            status = "enabled" if sched.enabled else "disabled"
            typer.echo(f"  [ok] {sched.name} ({sched.cron}) [{status}]")

    # Warnings
    if state.warnings:
        typer.echo(f"\nWarnings ({len(state.warnings)}):")
        for warning in state.warnings:
            typer.echo(f"  [!] {warning}")

    # Errors
    if state.errors:
        typer.echo(f"\nErrors ({len(state.errors)}):")
        for error in state.errors:
            typer.echo(f"  [x] {error}")

    typer.echo()
    if state.errors:
        typer.echo("Validation failed.")
        raise typer.Exit(code=1)
    else:
        typer.echo("Validation passed.")
