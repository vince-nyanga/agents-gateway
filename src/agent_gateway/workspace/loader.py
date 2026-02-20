"""Scan workspace directories and discover agents, skills, tools."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_gateway.workspace.agent import AgentDefinition, ScheduleConfig
from agent_gateway.workspace.parser import parse_markdown_file
from agent_gateway.workspace.skill import SkillDefinition
from agent_gateway.workspace.tool import ToolDefinition

logger = logging.getLogger(__name__)

_VALID_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass
class WorkspaceState:
    """The complete parsed state of a workspace."""

    path: Path
    agents: dict[str, AgentDefinition] = field(default_factory=dict)
    skills: dict[str, SkillDefinition] = field(default_factory=dict)
    tools: dict[str, ToolDefinition] = field(default_factory=dict)
    schedules: list[ScheduleConfig] = field(default_factory=list)
    root_system_prompt: str = ""  # From agents/AGENTS.md
    root_behavior_prompt: str = ""  # From agents/BEHAVIOR.md
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def resolve_agent_tools(self, agent: AgentDefinition) -> list[str]:
        """Gather deduplicated tool names from all skills an agent uses."""
        tool_names: list[str] = []
        seen: set[str] = set()
        for skill_name in agent.skills:
            skill = self.skills.get(skill_name)
            if skill:
                for t in skill.tools:
                    if t not in seen:
                        seen.add(t)
                        tool_names.append(t)
        return tool_names


def load_workspace(
    workspace_path: str | Path,
    retriever_names: frozenset[str] | None = None,
) -> WorkspaceState:
    """Load the full workspace. Never raises — collects warnings/errors.

    Args:
        workspace_path: Path to the workspace directory.
        retriever_names: Names of registered retrievers (for cross-reference validation).
    """
    path = Path(workspace_path)
    state = WorkspaceState(path=path)

    if not path.exists():
        state.errors.append(f"Workspace directory not found: {path}")
        return state

    if not path.is_dir():
        state.errors.append(f"Workspace path is not a directory: {path}")
        return state

    resolved_root = path.resolve()

    # Load root prompts
    _load_root_prompts(resolved_root, path, state)

    # Discover agents, skills, tools
    _load_agents(path / "agents", resolved_root, state)
    _load_skills(path / "skills", resolved_root, state)
    _load_tools(path / "tools", resolved_root, state)

    # Collect schedules from agents
    for agent in state.agents.values():
        state.schedules.extend(agent.schedules)

    # Cross-reference validation (warnings only)
    _validate_cross_references(state, retriever_names=retriever_names)

    agent_count = len(state.agents)
    skill_count = len(state.skills)
    tool_count = len(state.tools)
    schedule_count = len(state.schedules)
    logger.info(
        "Workspace loaded: %d agents, %d skills, %d tools, %d schedules",
        agent_count,
        skill_count,
        tool_count,
        schedule_count,
    )

    return state


def _is_safe_entry(entry: Path, resolved_root: Path) -> bool:
    """Check that a directory entry is safe to process."""
    if entry.is_symlink():
        logger.warning("Skipping symlink: %s", entry)
        return False
    if not entry.is_dir():
        return False
    if entry.name.startswith("."):
        return False
    if not entry.resolve().is_relative_to(resolved_root):
        logger.warning("Path escapes workspace: %s", entry)
        return False
    return True


def _is_valid_id(name: str) -> bool:
    """Check that a directory name is a valid entity ID."""
    return _VALID_ID_RE.match(name) is not None


def _load_root_prompts(resolved_root: Path, workspace: Path, state: WorkspaceState) -> None:
    agents_md = workspace / "agents" / "AGENTS.md"
    if agents_md.exists():
        parsed = parse_markdown_file(agents_md)
        state.root_system_prompt = parsed.content

    behavior_md = workspace / "agents" / "BEHAVIOR.md"
    if behavior_md.exists():
        parsed = parse_markdown_file(behavior_md)
        state.root_behavior_prompt = parsed.content


def _load_agents(agents_dir: Path, resolved_root: Path, state: WorkspaceState) -> None:
    if not agents_dir.exists():
        state.warnings.append("No agents/ directory found")
        return

    for entry in sorted(agents_dir.iterdir()):
        if not _is_safe_entry(entry, resolved_root):
            continue
        if not _is_valid_id(entry.name):
            state.warnings.append(f"Skipping agent directory with invalid ID: '{entry.name}'")
            continue

        agent = AgentDefinition.load(entry)
        if agent is not None:
            state.agents[agent.id] = agent
            logger.debug("Loaded agent: %s", agent.id)


def _load_skills(skills_dir: Path, resolved_root: Path, state: WorkspaceState) -> None:
    if not skills_dir.exists():
        return  # Skills are optional, no warning needed

    for entry in sorted(skills_dir.iterdir()):
        if not _is_safe_entry(entry, resolved_root):
            continue
        if not _is_valid_id(entry.name):
            state.warnings.append(f"Skipping skill directory with invalid ID: '{entry.name}'")
            continue

        skill = SkillDefinition.load(entry)
        if skill is not None:
            state.skills[skill.id] = skill
            logger.debug("Loaded skill: %s", skill.id)


def _load_tools(tools_dir: Path, resolved_root: Path, state: WorkspaceState) -> None:
    if not tools_dir.exists():
        return

    for entry in sorted(tools_dir.iterdir()):
        if not _is_safe_entry(entry, resolved_root):
            continue
        if not _is_valid_id(entry.name):
            state.warnings.append(f"Skipping tool directory with invalid ID: '{entry.name}'")
            continue

        tool = ToolDefinition.load(entry)
        if tool is not None:
            state.tools[tool.id] = tool
            logger.debug("Loaded tool: %s", tool.id)


def _validate_cross_references(
    state: WorkspaceState,
    retriever_names: frozenset[str] | None = None,
) -> None:
    """Check that skills reference existing tools, agents reference existing skills/retrievers."""
    registered_retrievers = retriever_names or frozenset()

    for skill in state.skills.values():
        for tool_name in skill.tools:
            if tool_name not in state.tools:
                state.warnings.append(f"Skill '{skill.id}' references unknown tool '{tool_name}'")

    for agent in state.agents.values():
        for skill_name in agent.skills:
            if skill_name not in state.skills:
                state.warnings.append(
                    f"Agent '{agent.id}' references unknown skill '{skill_name}'"
                )
        for retriever_name in agent.retrievers:
            if registered_retrievers and retriever_name not in registered_retrievers:
                state.warnings.append(
                    f"Agent '{agent.id}' references unknown retriever '{retriever_name}'"
                )
