"""Agent model — loaded from AGENT.md (+ optional BEHAVIOR.md)."""

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
    """Per-agent model configuration from AGENT.md frontmatter."""

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
    behavior_prompt: str = ""  # Content of BEHAVIOR.md (optional)

    # Public metadata from AGENT.md frontmatter
    description: str = ""
    display_name: str | None = None
    tags: list[str] = field(default_factory=list)
    version: str | None = None

    # Parsed from AGENT.md frontmatter
    skills: list[str] = field(default_factory=list)
    model: AgentModelConfig = field(default_factory=AgentModelConfig)
    schedules: list[ScheduleConfig] = field(default_factory=list)
    execution_mode: str = "sync"  # "sync" | "async"
    notifications: AgentNotificationConfig = field(default_factory=AgentNotificationConfig)
    input_schema: dict[str, Any] | None = None

    # RAG context
    context_content: list[str] = field(default_factory=list)  # loaded static file contents
    retrievers: list[str] = field(default_factory=list)  # named retriever references

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

        # Parse BEHAVIOR.md (optional)
        behavior_md = agent_dir / "BEHAVIOR.md"
        behavior_prompt = ""
        if behavior_md.exists():
            behavior_parsed = parse_markdown_file(behavior_md)
            behavior_prompt = behavior_parsed.content

        # Parse public metadata
        description = agent_meta.get("description", "")
        if not isinstance(description, str):
            logger.warning("Agent '%s': 'description' must be a string, ignoring", agent_id)
            description = ""

        display_name = agent_meta.get("display_name", None)
        if display_name is not None and not isinstance(display_name, str):
            logger.warning("Agent '%s': 'display_name' must be a string, ignoring", agent_id)
            display_name = None

        tags = agent_meta.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            logger.warning("Agent '%s': 'tags' must be a list of strings, ignoring", agent_id)
            tags = []

        raw_version = agent_meta.get("version", None)
        version = str(raw_version) if raw_version is not None else None

        skills = agent_meta.get("skills", [])

        if "tools" in agent_meta:
            logger.warning(
                "Agent %s has 'tools' in AGENT.md frontmatter; "
                "tools should be declared in SKILL.md instead",
                agent_id,
            )

        model_data = agent_meta.get("model", {})
        if not isinstance(model_data, dict):
            model_data = {}
        model_config = AgentModelConfig(
            name=model_data.get("name"),
            temperature=model_data.get("temperature"),
            max_tokens=model_data.get("max_tokens"),
            fallback=model_data.get("fallback"),
        )

        execution_mode_raw = agent_meta.get("execution_mode", "sync")
        execution_mode = (
            str(execution_mode_raw) if execution_mode_raw in ("sync", "async") else "sync"
        )

        schedules_data = agent_meta.get("schedules", [])
        schedules = _parse_schedules(schedules_data, agent_dir)

        raw_notif = agent_meta.get("notifications", {})
        notifications = _parse_notification_config(raw_notif, agent_dir)

        input_schema = _parse_input_schema(agent_meta.get("input_schema"), agent_dir)

        # Validate schedule contexts against input_schema at load time
        if input_schema:
            _validate_schedule_contexts(schedules, input_schema, agent_dir)

        # RAG context: auto-discover context/*.md + explicit frontmatter refs
        raw_context = agent_meta.get("context", [])
        context_paths: list[str] = raw_context if isinstance(raw_context, list) else []
        if raw_context and not isinstance(raw_context, list):
            logger.warning(
                "Agent '%s': 'context' must be a list of file paths, ignoring", agent_id
            )
        context_content = _load_context_files(agent_dir, context_paths)
        retrievers = agent_meta.get("retrievers", [])
        if not isinstance(retrievers, list) or not all(isinstance(r, str) for r in retrievers):
            logger.warning(
                "Agent '%s': 'retrievers' must be a list of strings, ignoring", agent_id
            )
            retrievers = []

        return cls(
            id=agent_id,
            path=agent_dir,
            agent_prompt=agent_parsed.content,
            behavior_prompt=behavior_prompt,
            description=description,
            display_name=display_name,
            tags=tags,
            version=version,
            skills=skills,
            model=model_config,
            schedules=schedules,
            execution_mode=execution_mode,
            notifications=notifications,
            input_schema=input_schema,
            context_content=context_content,
            retrievers=retrievers,
        )


def _load_context_files(
    agent_dir: Path,
    explicit_paths: list[str],
) -> list[str]:
    """Load static context files for an agent.

    Sources (combined, in order):
    1. Auto-discovered .md files from agent_dir/context/ (alphabetical)
    2. Explicit paths from AGENT.md frontmatter ``context:`` list
       (resolved relative to the workspace root, i.e. agent_dir's grandparent)
    """
    contents: list[str] = []

    # 1. Auto-discover context/ subdirectory
    context_dir = agent_dir / "context"
    if context_dir.is_dir() and not context_dir.is_symlink():
        for entry in sorted(context_dir.iterdir()):
            if entry.is_symlink():
                logger.warning("Skipping symlink in context dir: %s", entry)
                continue
            if not entry.is_file():
                continue
            if entry.suffix != ".md":
                logger.debug("Skipping non-markdown file in context dir: %s", entry)
                continue
            try:
                contents.append(entry.read_text(encoding="utf-8"))
            except OSError:
                logger.warning("Failed to read context file: %s", entry, exc_info=True)

    # 2. Explicit frontmatter paths
    if not explicit_paths:
        return contents

    # Workspace root is two levels up from agent dir: workspace/agents/<id>/
    workspace_root = agent_dir.parent.parent
    resolved_root = workspace_root.resolve()

    for raw_path in explicit_paths:
        if not isinstance(raw_path, str):
            logger.warning("Agent '%s': context path must be a string, skipping", agent_dir.name)
            continue
        target = workspace_root / raw_path
        # Path safety: prevent traversal outside workspace
        try:
            resolved = target.resolve()
        except OSError:
            logger.warning("Cannot resolve context path '%s' in %s", raw_path, agent_dir.name)
            continue
        if not resolved.is_relative_to(resolved_root):
            logger.warning(
                "Context path '%s' escapes workspace in agent '%s', skipping",
                raw_path,
                agent_dir.name,
            )
            continue
        if target.is_symlink():
            logger.warning("Skipping symlink context path: %s", raw_path)
            continue
        if not target.is_file():
            logger.warning("Context file '%s' not found for agent '%s'", raw_path, agent_dir.name)
            continue
        try:
            contents.append(target.read_text(encoding="utf-8"))
        except OSError:
            logger.warning("Failed to read context file: %s", target, exc_info=True)

    return contents


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
