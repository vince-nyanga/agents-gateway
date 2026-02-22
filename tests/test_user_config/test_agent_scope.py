"""Tests for agent scope and setup_schema parsing."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.agent import AgentDefinition


class TestAgentScope:
    """Test scope and setup_schema parsing from AGENT.md."""

    def test_default_scope_is_global(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "test-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("You are a test agent.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.scope == "global"
        assert agent.setup_schema is None

    def test_personal_scope(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "personal-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "scope: personal\n"
            "setup_schema:\n"
            "  type: object\n"
            "  required: [email]\n"
            "  properties:\n"
            "    email:\n"
            "      type: string\n"
            "    password:\n"
            "      type: string\n"
            "      sensitive: true\n"
            "---\n"
            "You are a personal agent."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.scope == "personal"
        assert agent.setup_schema is not None
        assert agent.setup_schema["type"] == "object"
        assert "email" in agent.setup_schema["required"]
        assert agent.setup_schema["properties"]["password"]["sensitive"] is True

    def test_invalid_scope_defaults_to_global(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "bad-scope"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nscope: invalid_value\n---\nYou are a test agent."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.scope == "global"

    def test_invalid_setup_schema_ignored(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "bad-schema"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nscope: personal\nsetup_schema: not-a-dict\n---\nYou are a test agent."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.scope == "personal"
        assert agent.setup_schema is None
