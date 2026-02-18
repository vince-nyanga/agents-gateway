"""Tests for agent-gateway version and help commands."""

from __future__ import annotations

from typer.testing import CliRunner

from agent_gateway.cli.main import app

runner = CliRunner()


def test_version_command() -> None:
    """version command prints the version."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "agent-gateway" in result.output


def test_help() -> None:
    """--help shows available commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "serve" in result.output
    assert "invoke" in result.output
    assert "check" in result.output
    assert "agents" in result.output
    assert "skills" in result.output
    assert "schedules" in result.output


def test_init_help() -> None:
    """init --help shows usage."""
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "project-name" in result.output.lower() or "PROJECT_NAME" in result.output


def test_check_help() -> None:
    """check --help shows usage."""
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "workspace" in result.output.lower()
