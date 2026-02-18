"""Agent model — loaded from AGENT.md (+ optional SOUL.md / CONFIG.md)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_gateway.workspace.parser import parse_markdown_file

logger = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    """A cron schedule for an agent."""

    name: str
    cron: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    timezone: str = "UTC"


@dataclass
class AgentModelConfig:
    """Per-agent model configuration from CONFIG.md."""

    name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    fallback: str | None = None


@dataclass
class AgentDefinition:
    """A fully parsed agent definition."""

    id: str  # Directory name (e.g., "underwriting")
    path: Path  # Directory path
    agent_prompt: str  # Content of AGENT.md
    soul_prompt: str = ""  # Content of SOUL.md (optional)

    # Parsed from AGENT.md frontmatter (with CONFIG.md override/merge)
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    model: AgentModelConfig = field(default_factory=AgentModelConfig)
    schedules: list[ScheduleConfig] = field(default_factory=list)

    @classmethod
    def load(cls, agent_dir: Path) -> AgentDefinition | None:
        """Load an agent from a directory.

        Returns None if AGENT.md is missing (not a valid agent dir).
        """
        agent_md = agent_dir / "AGENT.md"
        if not agent_md.exists():
            return None

        agent_id = agent_dir.name

        # Parse AGENT.md (required) — prompt body + optional frontmatter
        agent_parsed = parse_markdown_file(agent_md)
        if not agent_parsed.content.strip():
            logger.warning("Empty AGENT.md in %s, skipping agent", agent_dir)
            return None
        agent_meta = agent_parsed.metadata

        # Parse SOUL.md (optional)
        soul_md = agent_dir / "SOUL.md"
        soul_prompt = ""
        if soul_md.exists():
            soul_parsed = parse_markdown_file(soul_md)
            soul_prompt = soul_parsed.content

        # Parse CONFIG.md (optional — overrides/merges with AGENT.md frontmatter)
        config_md = agent_dir / "CONFIG.md"
        config_meta: dict[str, Any] = {}
        if config_md.exists():
            config_parsed = parse_markdown_file(config_md)
            config_meta = config_parsed.metadata

        # Merge lists: AGENT.md first, CONFIG.md appended, deduplicated
        skills = list(dict.fromkeys(agent_meta.get("skills", []) + config_meta.get("skills", [])))
        tools = list(dict.fromkeys(agent_meta.get("tools", []) + config_meta.get("tools", [])))

        # Scalars: CONFIG.md wins over AGENT.md
        model_data = config_meta.get("model") or agent_meta.get("model", {})
        if not isinstance(model_data, dict):
            model_data = {}
        model_config = AgentModelConfig(
            name=model_data.get("name"),
            temperature=model_data.get("temperature"),
            max_tokens=model_data.get("max_tokens"),
            fallback=model_data.get("fallback"),
        )

        schedules_data = config_meta.get("schedules") or agent_meta.get("schedules", [])
        schedules = []
        for s in schedules_data:
            try:
                schedules.append(
                    ScheduleConfig(
                        name=s["name"],
                        cron=s["cron"],
                        message=s["message"],
                        context=s.get("context", {}),
                        enabled=s.get("enabled", True),
                        timezone=s.get("timezone", "UTC"),
                    )
                )
            except (KeyError, TypeError) as e:
                logger.warning("Invalid schedule in %s: %s", agent_dir, e)

        return cls(
            id=agent_id,
            path=agent_dir,
            agent_prompt=agent_parsed.content,
            soul_prompt=soul_prompt,
            skills=skills,
            tools=tools,
            model=model_config,
            schedules=schedules,
        )
