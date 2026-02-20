"""Tests for schedule and notification parsing in AgentDefinition.load()."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.agent import AgentDefinition


def _write_agent(tmp_path: Path, frontmatter: str, body: str = "# Agent\n\nDo stuff.\n") -> Path:
    agents = tmp_path / "agents"
    agents.mkdir(exist_ok=True)
    agent_dir = agents / "test-agent"
    agent_dir.mkdir(exist_ok=True)
    (agent_dir / "AGENT.md").write_text(f"---\n{frontmatter}---\n\n{body}")
    return agent_dir


def test_valid_schedule_parsed(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'schedules:\n  - name: daily\n    cron: "0 9 * * *"\n    message: "Run"\n',
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.schedules) == 1
    assert agent.schedules[0].name == "daily"
    assert agent.schedules[0].cron == "0 9 * * *"


def test_schedule_with_timezone(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'schedules:\n  - name: daily\n    cron: "0 9 * * *"\n'
        '    message: "Run"\n    timezone: "Europe/London"\n',
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert agent.schedules[0].timezone == "Europe/London"


def test_schedule_invalid_timezone_skipped(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'schedules:\n  - name: daily\n    cron: "0 9 * * *"\n'
        '    message: "Run"\n    timezone: "Invalid/Nowhere"\n',
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.schedules) == 0


def test_schedule_invalid_cron_skipped(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'schedules:\n  - name: daily\n    cron: "bad cron"\n    message: "Run"\n',
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.schedules) == 0


def test_schedule_missing_required_field_skipped(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'schedules:\n  - name: daily\n    cron: "0 9 * * *"\n',  # missing message
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.schedules) == 0


def test_schedule_non_dict_entry_skipped(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        "schedules:\n  - not-a-dict\n",
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.schedules) == 0


def test_schedule_duplicate_name_skipped(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'schedules:\n  - name: daily\n    cron: "0 9 * * *"\n'
        '    message: "First"\n'
        '  - name: daily\n    cron: "0 10 * * *"\n'
        '    message: "Dupe"\n',
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.schedules) == 1
    assert agent.schedules[0].message == "First"


def test_notification_config_parsed(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'notifications:\n  on_complete:\n    - channel: log\n      target: ""\n',
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.notifications.on_complete) == 1
    assert agent.notifications.on_complete[0].channel == "log"


def test_notification_invalid_target_skipped(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        "notifications:\n  on_complete:\n    - not-a-dict\n",
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.notifications.on_complete) == 0


def test_notification_missing_channel_skipped(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'notifications:\n  on_complete:\n    - target: "test"\n',  # missing channel
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.notifications.on_complete) == 0


def test_notification_non_dict_raw(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        "notifications: not-a-dict\n",
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.notifications.on_complete) == 0


def test_notification_non_list_targets(tmp_path: Path) -> None:
    agent_dir = _write_agent(
        tmp_path,
        'notifications:\n  on_complete: "not-a-list"\n',
    )
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert len(agent.notifications.on_complete) == 0
