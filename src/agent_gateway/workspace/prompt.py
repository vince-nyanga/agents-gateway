"""Assemble layered system prompts for agents."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_gateway.workspace.agent import AgentDefinition
from agent_gateway.workspace.loader import WorkspaceState
from agent_gateway.workspace.skill import SkillDefinition


def assemble_system_prompt(
    agent: AgentDefinition,
    workspace: WorkspaceState,
) -> str:
    """Build the full system prompt for an agent.

    Layer order:
    1. Root AGENTS.md (shared system context)
    2. Root SOUL.md (shared personality)
    3. Agent AGENT.md (agent-specific instructions)
    4. Agent SOUL.md (agent-specific personality)
    5. Skill instructions (from each skill the agent uses)

    Note: Business context (gateway.yaml context block) is injected
    by the Gateway at invocation time, not during workspace loading.
    """
    parts: list[str] = []

    # 0. Current date/time
    now = datetime.now(UTC)
    parts.append(f"Current date and time (UTC): {now.strftime('%Y-%m-%d %H:%M')}")

    # 1. Root system prompt
    if workspace.root_system_prompt:
        parts.append(workspace.root_system_prompt)

    # 2. Root soul
    if workspace.root_soul_prompt:
        parts.append(workspace.root_soul_prompt)

    # 3. Agent prompt
    parts.append(agent.agent_prompt)

    # 4. Agent soul
    if agent.soul_prompt:
        parts.append(agent.soul_prompt)

    # 5. Skill instructions
    resolved_skills = [
        skill for name in agent.skills if (skill := workspace.skills.get(name)) is not None
    ]
    if resolved_skills:
        skill_section = _format_skills_section(resolved_skills)
        parts.append(skill_section)

    return "\n\n---\n\n".join(parts)


def _format_skills_section(skills: list[SkillDefinition]) -> str:
    """Format skill instructions for injection into the system prompt."""
    parts = ["## Available Skills\n"]
    for skill in skills:
        parts.append(f"### Skill: {skill.name}\n")
        if skill.description:
            parts.append(f"*{skill.description}*\n")
        if skill.instructions:
            parts.append(skill.instructions)
        parts.append("")
    return "\n".join(parts)
