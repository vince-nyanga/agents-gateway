"""Tests for agent-gateway check command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agent_gateway.cli.main import app

runner = CliRunner()

FIXTURES = Path(__file__).parent.parent / "fixtures" / "workspace"


def test_check_valid_workspace() -> None:
    """check passes for the fixture workspace."""
    result = runner.invoke(app, ["check", "--workspace", str(FIXTURES)])
    assert result.exit_code == 0
    assert "Validation passed" in result.output


def test_check_shows_agents() -> None:
    """check lists discovered agents."""
    result = runner.invoke(app, ["check", "--workspace", str(FIXTURES)])
    assert "test-agent" in result.output


def test_check_nonexistent_workspace() -> None:
    """check fails for a nonexistent workspace."""
    result = runner.invoke(app, ["check", "--workspace", "/tmp/does-not-exist-agw"])
    assert result.exit_code == 1
    assert "Validation failed" in result.output


def test_check_reports_warnings(tmp_path: Path) -> None:
    """check shows warnings for cross-reference issues."""
    # Create workspace with agent referencing unknown skill
    agents_dir = tmp_path / "agents" / "my-agent"
    agents_dir.mkdir(parents=True)
    (agents_dir / "AGENT.md").write_text("# Test Agent\n\nA test agent.\n")
    (agents_dir / "CONFIG.md").write_text("---\nskills:\n  - nonexistent-skill\n---\n")

    result = runner.invoke(app, ["check", "--workspace", str(tmp_path)])
    assert result.exit_code == 0  # warnings don't cause failure
    assert "nonexistent-skill" in result.output
