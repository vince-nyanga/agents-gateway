"""E2E tests for CLI commands against the example project workspace."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_gateway.cli.main import app

pytestmark = pytest.mark.e2e

runner = CliRunner()
EXAMPLE_WORKSPACE = str(
    Path(__file__).parent.parent.parent / "examples" / "test-project" / "workspace"
)


def test_check_command() -> None:
    """agent-gateway check validates the example workspace."""
    result = runner.invoke(app, ["check", "--workspace", EXAMPLE_WORKSPACE])
    assert result.exit_code == 0
    assert "Validation passed" in result.output


def test_check_lists_agents() -> None:
    """agent-gateway check lists both agents."""
    result = runner.invoke(app, ["check", "--workspace", EXAMPLE_WORKSPACE])
    assert "assistant" in result.output
    assert "scheduled-reporter" in result.output


def test_agents_command() -> None:
    """agent-gateway agents lists discovered agents."""
    result = runner.invoke(app, ["agents", "--workspace", EXAMPLE_WORKSPACE])
    assert result.exit_code == 0
    assert "assistant" in result.output
    assert "scheduled-reporter" in result.output


def test_skills_command() -> None:
    """agent-gateway skills lists discovered skills."""
    result = runner.invoke(app, ["skills", "--workspace", EXAMPLE_WORKSPACE])
    assert result.exit_code == 0
    assert "math-workflow" in result.output
