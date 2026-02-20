"""Tests for input_schema parsing in AgentDefinition.load()."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.agent import AgentDefinition


class TestInputSchemaParsing:
    def test_no_input_schema(self, tmp_path: Path) -> None:
        """Agent without input_schema has None."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("# Agent\n\nDoes things.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is None

    def test_input_schema_in_agent_md(self, tmp_path: Path) -> None:
        """input_schema parsed from AGENT.md frontmatter."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "input_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    deal_id:\n"
            "      type: string\n"
            "  required:\n"
            "    - deal_id\n"
            "---\n"
            "# Agent\n\nNeeds a deal."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is not None
        assert agent.input_schema["type"] == "object"
        assert "deal_id" in agent.input_schema["properties"]
        assert agent.input_schema["required"] == ["deal_id"]

    def test_input_schema_in_config_md_overrides(self, tmp_path: Path) -> None:
        """CONFIG.md input_schema overrides AGENT.md (scalar precedence)."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "input_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    old_field:\n"
            "      type: string\n"
            "---\n"
            "# Agent\n\nOld schema."
        )
        (agent_dir / "CONFIG.md").write_text(
            "---\n"
            "input_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    new_field:\n"
            "      type: integer\n"
            "---\n"
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is not None
        # CONFIG.md should win entirely
        assert "new_field" in agent.input_schema["properties"]
        assert "old_field" not in agent.input_schema["properties"]

    def test_invalid_schema_produces_none(self, tmp_path: Path) -> None:
        """Invalid JSON Schema in frontmatter is ignored with warning."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\ninput_schema:\n  type: bogus_type\n---\n# Agent\n\nBad schema."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is None

    def test_non_dict_schema_produces_none(self, tmp_path: Path) -> None:
        """Non-dict input_schema value is ignored."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\ninput_schema: just_a_string\n---\n# Agent\n\nString schema."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is None

    def test_schedule_input_validated_against_schema(self, tmp_path: Path) -> None:
        """Schedule with invalid input logs warning but still loads."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "input_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    deal_id:\n"
            "      type: string\n"
            "  required:\n"
            "    - deal_id\n"
            "schedules:\n"
            "  - name: daily\n"
            "    cron: '0 9 * * *'\n"
            "    message: 'Run daily'\n"
            "    input:\n"
            "      wrong_field: value\n"
            "---\n"
            "# Agent\n\nScheduled agent."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is not None
        # Schedule still loads despite invalid input
        assert len(agent.schedules) == 1
        assert agent.schedules[0].name == "daily"

    def test_schedule_input_valid_against_schema(self, tmp_path: Path) -> None:
        """Schedule with valid input loads without issues."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "input_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    deal_id:\n"
            "      type: string\n"
            "  required:\n"
            "    - deal_id\n"
            "schedules:\n"
            "  - name: daily\n"
            "    cron: '0 9 * * *'\n"
            "    message: 'Run daily'\n"
            "    input:\n"
            "      deal_id: D-123\n"
            "---\n"
            "# Agent\n\nScheduled agent."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert len(agent.schedules) == 1

    def test_complex_schema_with_enum(self, tmp_path: Path) -> None:
        """Schema with enum and nested properties."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "input_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    tier:\n"
            "      type: string\n"
            "      enum:\n"
            "        - standard\n"
            "        - premium\n"
            "    amount:\n"
            "      type: number\n"
            "---\n"
            "# Agent\n\nComplex schema."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is not None
        assert agent.input_schema["properties"]["tier"]["enum"] == ["standard", "premium"]
