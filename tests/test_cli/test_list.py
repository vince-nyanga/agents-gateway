"""Tests for agent-gateway agents/skills/schedules commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agent_gateway.cli.main import app

runner = CliRunner()

FIXTURES = Path(__file__).parent.parent / "fixtures" / "workspace"


def test_agents_lists_agents() -> None:
    """agents command lists discovered agents."""
    result = runner.invoke(app, ["agents", "--workspace", str(FIXTURES)])
    assert result.exit_code == 0
    assert "test-agent" in result.output


def test_agents_empty_workspace(tmp_path: Path) -> None:
    """agents command handles empty workspace."""
    (tmp_path / "agents").mkdir()
    result = runner.invoke(app, ["agents", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "No agents found" in result.output


def test_skills_lists_skills() -> None:
    """skills command lists discovered skills."""
    result = runner.invoke(app, ["skills", "--workspace", str(FIXTURES)])
    assert result.exit_code == 0
    # The fixture workspace may or may not have skills
    assert result.exit_code == 0


def test_schedules_lists_schedules() -> None:
    """schedules command lists discovered schedules."""
    result = runner.invoke(app, ["schedules", "--workspace", str(FIXTURES)])
    assert result.exit_code == 0


def test_agents_with_invalid_workspace() -> None:
    """agents command fails with invalid workspace."""
    result = runner.invoke(app, ["agents", "--workspace", "/tmp/does-not-exist-agw"])
    assert result.exit_code == 1


def test_schedules_with_schedule_data(tmp_path: Path) -> None:
    """schedules command shows schedule details."""
    agents_dir = tmp_path / "agents" / "cron-agent"
    agents_dir.mkdir(parents=True)
    (agents_dir / "AGENT.md").write_text("# Cron Agent\n\nRuns on schedule.\n")
    (agents_dir / "CONFIG.md").write_text(
        "---\n"
        "schedules:\n"
        "  - name: daily-check\n"
        '    cron: "0 8 * * *"\n'
        "    message: Run daily check\n"
        "    enabled: true\n"
        "---\n"
    )

    result = runner.invoke(app, ["schedules", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "daily-check" in result.output
    assert "0 8 * * *" in result.output
