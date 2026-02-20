"""Tests for prompt assembly."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.loader import load_workspace
from agent_gateway.workspace.prompt import assemble_system_prompt


class TestAssembleSystemPrompt:
    async def test_basic_assembly(self, tmp_path: Path) -> None:
        """Agent prompt is always included."""
        agents_dir = tmp_path / "agents" / "my-agent"
        agents_dir.mkdir(parents=True)
        (agents_dir / "AGENT.md").write_text("# My Agent\n\nYou are helpful.")

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)
        assert "You are helpful" in prompt

    async def test_root_prompts_included(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "AGENTS.md").write_text("# System\n\nShared context.")
        (agents_dir / "BEHAVIOR.md").write_text("# Behavior\n\nBe professional.")

        agent_dir = agents_dir / "my-agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("# Agent\n\nSpecific instructions.")

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)

        assert "Shared context" in prompt
        assert "Be professional" in prompt
        assert "Specific instructions" in prompt
        # Check order: root system before agent
        assert prompt.index("Shared context") < prompt.index("Specific instructions")

    async def test_agent_behavior_included(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nInstructions.")
        (agent_dir / "BEHAVIOR.md").write_text("# Behavior\n\nFriendly.")

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)
        assert "Friendly" in prompt

    async def test_skills_injected(self, tmp_path: Path) -> None:
        # Create agent with skill reference
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nskills:\n  - math-workflow\n---\n# Agent\n\nUses skills."
        )

        # Create skill
        skill_dir = tmp_path / "skills" / "math-workflow"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: math-workflow\ndescription: Do math\n---\n# Math\n\nBreak into steps."
        )

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)
        assert "math-workflow" in prompt
        assert "Do math" in prompt
        assert "Break into steps" in prompt

    async def test_missing_skill_skipped(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nskills:\n  - nonexistent\n---\n# Agent\n\nHello."
        )

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)
        assert "nonexistent" not in prompt
        assert "Hello" in prompt

    async def test_separator_between_layers(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "AGENTS.md").write_text("# System\n\nRoot prompt.")

        agent_dir = agents_dir / "my-agent"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("# Agent\n\nAgent prompt.")

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)
        assert "\n\n---\n\n" in prompt
