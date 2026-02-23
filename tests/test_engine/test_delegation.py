"""Tests for agent-to-agent delegation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_gateway.config import GatewayConfig, GuardrailsConfig
from agent_gateway.engine.delegation import run_delegation
from agent_gateway.engine.models import ExecutionResult, StopReason
from agent_gateway.persistence.domain import ExecutionRecord
from agent_gateway.workspace.agent import AgentDefinition


class TestRunDelegation:
    """Tests for the run_delegation function."""

    @pytest.fixture
    def mock_gateway(self) -> MagicMock:
        gw = MagicMock()
        gw._config = GatewayConfig()
        gw._config.guardrails = GuardrailsConfig(max_delegation_depth=3)
        return gw

    @pytest.mark.asyncio
    async def test_permission_denied(self, mock_gateway: MagicMock) -> None:
        """Returns error when agent_id not in delegates_to."""
        result = await run_delegation(
            mock_gateway,
            caller_agent_id="coordinator",
            delegates_to=["writer"],
            execution_id="exec-1",
            root_execution_id="root-1",
            delegation_depth=0,
            user_id=None,
            agent_id="hacker",
            message="do something",
        )
        assert "Error" in result
        assert "not allowed" in result
        assert "hacker" in result

    @pytest.mark.asyncio
    async def test_max_depth_reached(self, mock_gateway: MagicMock) -> None:
        """Returns error when max delegation depth is reached."""
        result = await run_delegation(
            mock_gateway,
            caller_agent_id="coordinator",
            delegates_to=["writer"],
            execution_id="exec-1",
            root_execution_id="root-1",
            delegation_depth=3,  # at max
            user_id=None,
            agent_id="writer",
            message="do something",
        )
        assert "Error" in result
        assert "Maximum delegation depth" in result

    @pytest.mark.asyncio
    async def test_successful_delegation(self, mock_gateway: MagicMock) -> None:
        """Successfully delegates and returns result text."""
        mock_result = ExecutionResult(
            raw_text="I completed the task.",
            stop_reason=StopReason.COMPLETED,
        )
        mock_gateway.invoke = AsyncMock(return_value=mock_result)

        result = await run_delegation(
            mock_gateway,
            caller_agent_id="coordinator",
            delegates_to=["writer"],
            execution_id="exec-1",
            root_execution_id="root-1",
            delegation_depth=0,
            user_id=None,
            agent_id="writer",
            message="write a report",
        )
        assert result == "I completed the task."
        mock_gateway.invoke.assert_awaited_once_with(
            agent_id="writer",
            message="write a report",
            input=None,
            parent_execution_id="exec-1",
            root_execution_id="root-1",
            delegation_depth=1,
        )

    @pytest.mark.asyncio
    async def test_delegation_exception_handling(self, mock_gateway: MagicMock) -> None:
        """Returns error string when delegation raises."""
        mock_gateway.invoke = AsyncMock(side_effect=ValueError("Agent not found"))

        result = await run_delegation(
            mock_gateway,
            caller_agent_id="coordinator",
            delegates_to=["writer"],
            execution_id="exec-1",
            root_execution_id="root-1",
            delegation_depth=0,
            user_id=None,
            agent_id="writer",
            message="write a report",
        )
        assert "Error" in result
        assert "failed" in result


class TestAgentDefinitionDelegatesTo:
    """Tests for delegates_to parsing from frontmatter."""

    def test_delegates_to_parsed(self, tmp_path: Path) -> None:
        """delegates_to list is parsed from AGENT.md frontmatter."""
        agent_dir = tmp_path / "coordinator"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "description: Coordinator\n"
            "delegates_to:\n"
            "  - writer\n"
            "  - researcher\n"
            "---\n"
            "You are a coordinator agent.\n"
        )
        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.delegates_to == ["writer", "researcher"]

    def test_delegates_to_empty_by_default(self, tmp_path: Path) -> None:
        """delegates_to defaults to empty list."""
        agent_dir = tmp_path / "basic"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\ndescription: Basic agent\n---\nYou are a basic agent.\n"
        )
        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.delegates_to == []

    def test_delegates_to_invalid_ignored(self, tmp_path: Path) -> None:
        """Invalid delegates_to value is ignored."""
        agent_dir = tmp_path / "bad"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\ndescription: Bad agent\ndelegates_to: not-a-list\n---\nYou are a bad agent.\n"
        )
        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.delegates_to == []


class TestExecutionRecordDelegationFields:
    """Tests for delegation fields on ExecutionRecord."""

    def test_default_values(self) -> None:
        record = ExecutionRecord(id="1", agent_id="test")
        assert record.parent_execution_id is None
        assert record.root_execution_id is None
        assert record.delegation_depth == 0

    def test_set_values(self) -> None:
        record = ExecutionRecord(
            id="child-1",
            agent_id="writer",
            parent_execution_id="parent-1",
            root_execution_id="root-1",
            delegation_depth=2,
        )
        assert record.parent_execution_id == "parent-1"
        assert record.root_execution_id == "root-1"
        assert record.delegation_depth == 2
