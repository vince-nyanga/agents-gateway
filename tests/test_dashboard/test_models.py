"""Tests for dashboard view models."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.dashboard.models import AgentCard
from agent_gateway.persistence.domain import UserAgentConfig
from agent_gateway.workspace.agent import AgentDefinition


def _make_agent(agent_id: str = "test-agent", scope: str = "global") -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        path=Path("/tmp/agents") / agent_id,
        agent_prompt="You are a test agent.",
        display_name="Test Agent",
        scope=scope,
    )


def test_agent_card_global_agent():
    agent = _make_agent()
    card = AgentCard.from_definition(agent)
    assert card.scope == "global"
    assert card.is_personal is False
    assert card.user_configured is False


def test_agent_card_personal_unconfigured():
    agent = _make_agent(scope="personal")
    card = AgentCard.from_definition(agent)
    assert card.scope == "personal"
    assert card.is_personal is True
    assert card.user_configured is False


def test_agent_card_personal_configured():
    agent = _make_agent(scope="personal")
    config = UserAgentConfig(
        user_id="user-1",
        agent_id="test-agent",
        setup_completed=True,
    )
    card = AgentCard.from_definition(agent, user_config=config)
    assert card.is_personal is True
    assert card.user_configured is True


def test_agent_card_personal_incomplete_config():
    agent = _make_agent(scope="personal")
    config = UserAgentConfig(
        user_id="user-1",
        agent_id="test-agent",
        setup_completed=False,
    )
    card = AgentCard.from_definition(agent, user_config=config)
    assert card.is_personal is True
    assert card.user_configured is False
