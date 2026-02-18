"""Tests for agent-gateway invoke command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agent_gateway.cli.main import app

runner = CliRunner()

FIXTURES = Path(__file__).parent.parent / "fixtures" / "workspace"


def test_invoke_unknown_agent() -> None:
    """invoke with unknown agent prints error."""
    result = runner.invoke(app, ["invoke", "nonexistent", "hello", "--workspace", str(FIXTURES)])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_invoke_invalid_workspace() -> None:
    """invoke with invalid workspace prints error."""
    result = runner.invoke(
        app, ["invoke", "test-agent", "hello", "--workspace", "/tmp/does-not-exist-agw"]
    )
    assert result.exit_code == 1


def test_invoke_valid_agent() -> None:
    """invoke with valid agent runs (placeholder result for now)."""
    result = runner.invoke(app, ["invoke", "test-agent", "hello", "--workspace", str(FIXTURES)])
    # Should complete (even if result is placeholder until Phase 8)
    assert result.exit_code == 0


def test_invoke_json_output() -> None:
    """invoke --json outputs JSON format."""
    result = runner.invoke(
        app, ["invoke", "test-agent", "hello", "--workspace", str(FIXTURES), "--json"]
    )
    assert result.exit_code == 0
    assert "{" in result.output
