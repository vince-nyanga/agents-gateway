"""Tests for prompt assembly with RAG context layers."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.context.registry import RetrieverRegistry
from agent_gateway.workspace.loader import load_workspace
from agent_gateway.workspace.prompt import assemble_system_prompt


class _FakeRetriever:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        return self._chunks

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _FailingRetriever:
    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        raise RuntimeError("retriever error")

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass


class TestPromptWithStaticContext:
    async def test_static_context_in_prompt(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nInstructions.")
        (context_dir / "guide.md").write_text("Style guide content.")

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)

        assert "## Reference Material" in prompt
        assert "Style guide content." in prompt

    async def test_static_context_after_agent_behavior(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nAgent instructions.")
        (agent_dir / "BEHAVIOR.md").write_text("# Behavior\n\nBe professional.")
        (context_dir / "guide.md").write_text("Guide content.")

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)

        assert prompt.index("Be professional") < prompt.index("Reference Material")

    async def test_static_context_before_skills(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nskills:\n  - test-skill\n---\n# Agent\n\nInstructions."
        )
        (context_dir / "guide.md").write_text("Guide content.")

        skill_dir = tmp_path / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\n# Skill\n\nDo things."
        )

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state)

        assert prompt.index("Reference Material") < prompt.index("Available Skills")


class TestPromptWithDynamicRetriever:
    async def test_retriever_results_in_prompt(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - test-retriever\n---\n# Agent\n\nInstructions."
        )

        registry = RetrieverRegistry()
        registry.register("test-retriever", _FakeRetriever(["Chunk 1", "Chunk 2"]))

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(
            agent, state, query="hello", retriever_registry=registry
        )

        assert "## Retrieved Context" in prompt
        assert "Chunk 1" in prompt
        assert "Chunk 2" in prompt

    async def test_no_query_skips_retriever(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - test-retriever\n---\n# Agent\n\nInstructions."
        )

        registry = RetrieverRegistry()
        registry.register("test-retriever", _FakeRetriever(["Should not appear"]))

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state, retriever_registry=registry)

        assert "Retrieved Context" not in prompt

    async def test_no_registry_skips_retriever(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - test-retriever\n---\n# Agent\n\nInstructions."
        )

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state, query="hello")

        assert "Retrieved Context" not in prompt

    async def test_failing_retriever_skipped(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - bad-retriever\n---\n# Agent\n\nInstructions."
        )

        registry = RetrieverRegistry()
        registry.register("bad-retriever", _FailingRetriever())

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        # Should not raise
        prompt = await assemble_system_prompt(
            agent, state, query="hello", retriever_registry=registry
        )

        assert "Retrieved Context" not in prompt
        assert "Instructions" in prompt

    async def test_agent_without_retrievers_unaffected(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nJust instructions.")

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        prompt = await assemble_system_prompt(agent, state, query="hello")

        assert "Retrieved Context" not in prompt
        assert "Reference Material" not in prompt
        assert "Just instructions" in prompt


class TestCrossReferenceValidation:
    def test_unknown_retriever_warning(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - nonexistent\n---\n# Agent\n\nHello."
        )

        state = load_workspace(tmp_path, retriever_names=frozenset(["other-retriever"]))
        assert any("nonexistent" in w for w in state.warnings)

    def test_known_retriever_no_warning(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - my-retriever\n---\n# Agent\n\nHello."
        )

        state = load_workspace(tmp_path, retriever_names=frozenset(["my-retriever"]))
        assert not any("retriever" in w for w in state.warnings)

    def test_no_retriever_names_skips_validation(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - anything\n---\n# Agent\n\nHello."
        )

        state = load_workspace(tmp_path)
        # No retriever_names passed, so no validation warning
        assert not any("retriever" in w for w in state.warnings)
