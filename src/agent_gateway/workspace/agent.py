"""Agent model — loaded from AGENT.md (+ optional SOUL.md / CONFIG.md)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_gateway.notifications.models import AgentNotificationConfig, NotificationTarget
from agent_gateway.workspace.parser import parse_markdown_file

logger = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    """A cron schedule for an agent."""

    name: str
    cron: str
    message: str
    input: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    timezone: str | None = None


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
    execution_mode: str = "sync"  # "sync" | "async"
    notifications: AgentNotificationConfig = field(default_factory=AgentNotificationConfig)
    input_schema: dict[str, Any] | None = None

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

        # Execution mode: CONFIG.md wins over AGENT.md (scalar precedence)
        execution_mode_raw = config_meta.get("execution_mode") or agent_meta.get(
            "execution_mode", "sync"
        )
        execution_mode = (
            str(execution_mode_raw) if execution_mode_raw in ("sync", "async") else "sync"
        )

        schedules_data = config_meta.get("schedules") or agent_meta.get("schedules", [])
        schedules = _parse_schedules(schedules_data, agent_dir)

        # Notifications: CONFIG.md wins (scalar precedence, same as model/execution_mode)
        raw_notif = config_meta.get("notifications") or agent_meta.get("notifications", {})
        notifications = _parse_notification_config(raw_notif, agent_dir)

        # Input schema: CONFIG.md wins (scalar precedence)
        input_schema = _parse_input_schema(
            config_meta.get("input_schema") or agent_meta.get("input_schema"),
            agent_dir,
        )

        # Validate schedule contexts against input_schema at load time
        if input_schema:
            _validate_schedule_contexts(schedules, input_schema, agent_dir)

        return cls(
            id=agent_id,
            path=agent_dir,
            agent_prompt=agent_parsed.content,
            soul_prompt=soul_prompt,
            skills=skills,
            tools=tools,
            model=model_config,
            schedules=schedules,
            execution_mode=execution_mode,
            notifications=notifications,
            input_schema=input_schema,
        )


def _parse_input_schema(
    raw: Any,
    agent_dir: Path,
) -> dict[str, Any] | None:
    """Parse and validate an input_schema from agent frontmatter.

    Returns the schema dict if valid, None otherwise.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning("Invalid input_schema (not a dict) in %s, ignoring", agent_dir)
        return None

    # Validate that the schema itself is a valid JSON Schema
    import jsonschema

    try:
        jsonschema.Draft202012Validator.check_schema(raw)
    except jsonschema.SchemaError as e:
        logger.warning(
            "Invalid JSON Schema in input_schema for %s: %s, ignoring",
            agent_dir,
            e.message,
        )
        return None

    return raw


def _validate_schedule_contexts(
    schedules: list[ScheduleConfig],
    input_schema: dict[str, Any],
    agent_dir: Path,
) -> None:
    """Validate schedule inputs against the agent's input_schema at load time."""
    import jsonschema

    for schedule in schedules:
        try:
            jsonschema.validate(instance=schedule.input, schema=input_schema)
        except jsonschema.ValidationError as e:
            logger.warning(
                "Schedule '%s' in %s has input that violates input_schema: %s",
                schedule.name,
                agent_dir,
                e.message,
            )


def _parse_schedules(
    schedules_data: list[Any],
    agent_dir: Path,
) -> list[ScheduleConfig]:
    """Parse and validate schedule definitions from agent frontmatter."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from apscheduler.triggers.cron import CronTrigger

    schedules: list[ScheduleConfig] = []
    seen_names: set[str] = set()

    for s in schedules_data:
        if not isinstance(s, dict):
            logger.warning("Invalid schedule entry (not a dict) in %s", agent_dir)
            continue
        try:
            name = s["name"]
            cron_expr = s["cron"]
            message = s["message"]
        except KeyError as e:
            logger.warning("Invalid schedule in %s: missing required field %s", agent_dir, e)
            continue

        # Enforce uniqueness per agent
        if name in seen_names:
            logger.warning("Duplicate schedule name '%s' in %s, skipping", name, agent_dir)
            continue
        seen_names.add(name)

        tz: str | None = s.get("timezone")

        # Validate timezone if explicitly set
        if tz is not None:
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, KeyError):
                logger.warning(
                    "Invalid timezone '%s' for schedule '%s' in %s, skipping",
                    tz,
                    name,
                    agent_dir,
                )
                continue

        # Validate cron expression
        try:
            CronTrigger.from_crontab(cron_expr, timezone=tz or "UTC")
        except (ValueError, KeyError) as e:
            logger.warning(
                "Invalid cron expression '%s' for schedule '%s' in %s: %s",
                cron_expr,
                name,
                agent_dir,
                e,
            )
            continue

        schedules.append(
            ScheduleConfig(
                name=name,
                cron=cron_expr,
                message=message,
                input=s.get("input", {}),
                enabled=s.get("enabled", True),
                timezone=tz,
            )
        )

    return schedules


def _parse_notification_config(
    raw: dict[str, Any],
    agent_dir: Path,
) -> AgentNotificationConfig:
    """Parse notifications block from agent frontmatter."""
    if not isinstance(raw, dict):
        return AgentNotificationConfig()

    def _parse_targets(items: Any) -> list[NotificationTarget]:
        if not isinstance(items, list):
            return []
        targets: list[NotificationTarget] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                targets.append(
                    NotificationTarget(
                        channel=item["channel"],
                        target=item.get("target", ""),
                        template=item.get("template"),
                        url=item.get("url"),
                        payload_template=item.get("payload_template"),
                    )
                )
            except (KeyError, TypeError) as e:
                logger.warning("Invalid notification target in %s: %s", agent_dir, e)
        return targets

    return AgentNotificationConfig(
        on_complete=_parse_targets(raw.get("on_complete")),
        on_error=_parse_targets(raw.get("on_error")),
        on_timeout=_parse_targets(raw.get("on_timeout")),
    )
