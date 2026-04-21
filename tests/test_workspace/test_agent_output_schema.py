"""Tests for output_schema parsing in AgentDefinition.load()."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.agent import AgentDefinition


class TestOutputSchemaParsing:
    def test_no_output_schema(self, tmp_path: Path) -> None:
        """Agent without output_schema has None."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("# Agent\n\nDoes things.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.output_schema is None
        assert agent._pydantic_output_model is None

    def test_output_schema_in_agent_md(self, tmp_path: Path) -> None:
        """output_schema is parsed from AGENT.md frontmatter."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "output_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    answer:\n"
            "      type: string\n"
            "  required:\n"
            "    - answer\n"
            "---\n"
            "# Agent\n\nReturns structured output."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.output_schema is not None
        assert agent.output_schema["type"] == "object"
        assert "answer" in agent.output_schema["properties"]
        assert agent.output_schema["required"] == ["answer"]

    def test_invalid_schema_produces_none(self, tmp_path: Path) -> None:
        """Invalid JSON Schema in frontmatter is ignored with warning."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\noutput_schema:\n  type: totally_bogus_type\n---\n# Agent"
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.output_schema is None

    def test_non_dict_schema_produces_none(self, tmp_path: Path) -> None:
        """Non-dict output_schema value is ignored."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("---\noutput_schema: just_a_string\n---\n# Agent")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.output_schema is None

    def test_input_and_output_schema_coexist(self, tmp_path: Path) -> None:
        """Both input_schema and output_schema can be declared together."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "input_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    q:\n"
            "      type: string\n"
            "output_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    answer:\n"
            "      type: string\n"
            "---\n"
            "# Agent"
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.input_schema is not None
        assert agent.output_schema is not None
        assert "q" in agent.input_schema["properties"]
        assert "answer" in agent.output_schema["properties"]

    def test_complex_output_schema_with_nested(self, tmp_path: Path) -> None:
        """Nested/array properties are parsed correctly."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\n"
            "output_schema:\n"
            "  type: object\n"
            "  properties:\n"
            "    skills:\n"
            "      type: array\n"
            "      items:\n"
            "        type: string\n"
            "    score:\n"
            "      type: number\n"
            "      minimum: 0\n"
            "  additionalProperties: false\n"
            "---\n"
            "# Agent"
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.output_schema is not None
        assert agent.output_schema["properties"]["skills"]["type"] == "array"
        assert agent.output_schema["additionalProperties"] is False
