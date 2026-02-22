"""Tests for user instructions injection into system prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_gateway.workspace.agent import AgentDefinition
from agent_gateway.workspace.loader import WorkspaceState
from agent_gateway.workspace.prompt import assemble_system_prompt


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceState:
    return WorkspaceState(
        path=tmp_path,
        agents={},
        skills={},
        tools={},
        schedules=[],
        root_system_prompt="",
        root_behavior_prompt="",
        warnings=[],
        errors=[],
    )


@pytest.fixture
def agent(tmp_path: Path) -> AgentDefinition:
    agent_dir = tmp_path / "agents" / "test"
    agent_dir.mkdir(parents=True)
    return AgentDefinition(
        id="test",
        path=agent_dir,
        agent_prompt="You are a helpful assistant.",
        scope="personal",
    )


class TestUserInstructionsInjection:
    async def test_user_instructions_included_in_prompt(
        self, agent: AgentDefinition, workspace: WorkspaceState
    ) -> None:
        prompt = await assemble_system_prompt(
            agent,
            workspace,
            user_instructions="Always respond in French.",
        )
        assert "## User Instructions" in prompt
        assert "Always respond in French." in prompt
        assert "<user-instructions>" in prompt

    async def test_no_user_instructions_section_when_none(
        self, agent: AgentDefinition, workspace: WorkspaceState
    ) -> None:
        prompt = await assemble_system_prompt(agent, workspace)
        assert "## User Instructions" not in prompt

    async def test_user_instructions_after_agent_prompt(
        self, agent: AgentDefinition, workspace: WorkspaceState
    ) -> None:
        prompt = await assemble_system_prompt(
            agent,
            workspace,
            user_instructions="Custom instruction",
            memory_block="Some memory",
        )
        agent_pos = prompt.index("You are a helpful assistant.")
        user_pos = prompt.index("Custom instruction")
        memory_pos = prompt.index("Some memory")
        # User instructions should come after agent prompt but before memory
        assert agent_pos < user_pos < memory_pos
