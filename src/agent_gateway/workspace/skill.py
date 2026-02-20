"""Skill model — loaded from SKILL.md.

Skills are composable workflow units that own tools and optionally define
multi-step execution plans with sequencing and parallel fan-out/fan-in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_gateway.workspace.parser import parse_markdown_file

logger = logging.getLogger(__name__)


@dataclass
class ToolStep:
    """A single tool invocation in a parallel fan-out."""

    tool: str
    input: dict[str, str] = field(default_factory=dict)


@dataclass
class SkillStep:
    """One step in a skill workflow.

    Exactly one of ``tool``, ``tools``, or ``prompt`` must be set:
    - ``tool``: run a single tool
    - ``tools``: parallel fan-out — run multiple tools concurrently
    - ``prompt``: LLM-only step (no tool call)
    """

    name: str
    tool: str | None = None
    tools: list[ToolStep] | None = None
    prompt: str | None = None
    system_prompt: str | None = None  # Override for prompt steps; defaults to built-in message
    input: dict[str, str] = field(default_factory=dict)


@dataclass
class SkillDefinition:
    """A fully parsed skill definition."""

    id: str  # Directory name
    path: Path  # Directory path
    name: str  # From frontmatter
    description: str  # From frontmatter
    tools: list[str] = field(default_factory=list)  # Tool names this skill uses
    instructions: str = ""  # Markdown body (injected into prompt)
    steps: list[SkillStep] = field(default_factory=list)  # Workflow steps (optional)

    @property
    def has_workflow(self) -> bool:
        """Whether this skill defines a step-based workflow."""
        return len(self.steps) > 0

    @classmethod
    def load(cls, skill_dir: Path) -> SkillDefinition | None:
        """Load a skill from a directory. Returns None if SKILL.md missing."""
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        parsed = parse_markdown_file(skill_md)
        meta = parsed.metadata

        name = meta.get("name", skill_dir.name)
        description = meta.get("description", "")

        if not description:
            logger.warning("Skill %s has no description", skill_dir.name)

        steps = _parse_steps(meta.get("steps", []), skill_dir)

        return cls(
            id=skill_dir.name,
            path=skill_dir,
            name=name,
            description=description,
            tools=meta.get("tools", []),
            instructions=parsed.content,
            steps=steps,
        )


def _parse_steps(raw_steps: list[Any], skill_dir: Path) -> list[SkillStep]:
    """Parse workflow steps from SKILL.md frontmatter."""
    if not isinstance(raw_steps, list):
        return []

    steps: list[SkillStep] = []
    seen_names: set[str] = set()

    for raw in raw_steps:
        if not isinstance(raw, dict):
            logger.warning("Invalid step (not a dict) in skill %s, skipping", skill_dir.name)
            continue

        step_name = raw.get("name")
        if not step_name or not isinstance(step_name, str):
            logger.warning("Step missing 'name' in skill %s, skipping", skill_dir.name)
            continue

        if step_name in seen_names:
            logger.warning(
                "Duplicate step name '%s' in skill %s, skipping", step_name, skill_dir.name
            )
            continue
        seen_names.add(step_name)

        step_input = raw.get("input", {})
        if not isinstance(step_input, dict):
            step_input = {}

        # Determine step type
        tool = raw.get("tool")
        tools_raw = raw.get("tools")
        prompt = raw.get("prompt")

        # Validate exactly one of tool/tools/prompt is set
        set_count = sum(1 for v in (tool, tools_raw, prompt) if v is not None)
        if set_count != 1:
            logger.warning(
                "Step '%s' in skill %s must have exactly one of tool, tools, or prompt; skipping",
                step_name,
                skill_dir.name,
            )
            continue

        parsed_tools: list[ToolStep] | None = None
        if tools_raw is not None:
            parsed_tools = _parse_tool_steps(tools_raw, step_name, skill_dir)
            if not parsed_tools:
                continue  # Warning already logged

        system_prompt = raw.get("system_prompt")
        steps.append(
            SkillStep(
                name=step_name,
                tool=tool if isinstance(tool, str) else None,
                tools=parsed_tools,
                prompt=prompt if isinstance(prompt, str) else None,
                system_prompt=system_prompt if isinstance(system_prompt, str) else None,
                input={str(k): str(v) for k, v in step_input.items()},
            )
        )

    return steps


def _parse_tool_steps(raw_tools: Any, step_name: str, skill_dir: Path) -> list[ToolStep] | None:
    """Parse parallel tool steps for a fan-out step."""
    if not isinstance(raw_tools, list) or not raw_tools:
        logger.warning(
            "Step '%s' in skill %s has invalid 'tools' (must be non-empty list)",
            step_name,
            skill_dir.name,
        )
        return None

    tool_steps: list[ToolStep] = []
    for item in raw_tools:
        if not isinstance(item, dict) or "tool" not in item:
            logger.warning(
                "Invalid tool entry in step '%s' of skill %s, skipping",
                step_name,
                skill_dir.name,
            )
            continue
        item_input = item.get("input", {})
        if not isinstance(item_input, dict):
            item_input = {}
        tool_steps.append(
            ToolStep(
                tool=item["tool"],
                input={str(k): str(v) for k, v in item_input.items()},
            )
        )

    if not tool_steps:
        logger.warning(
            "Step '%s' in skill %s has no valid tool entries",
            step_name,
            skill_dir.name,
        )
        return None

    return tool_steps
