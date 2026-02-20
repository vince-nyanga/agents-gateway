"""Tests for prompt assembly with RAG context layers."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_gateway.config import ContextRetrievalConfig
from agent_gateway.context.registry import RetrieverRegistry
from agent_gateway.workspace.loader import load_workspace
from agent_gateway.workspace.prompt import assemble_system_prompt

from .conftest import FailingRetriever, FakeRetriever


class _SlowRetriever:
    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        await asyncio.sleep(60)  # way beyond timeout
        return ["should not appear"]

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
        registry.register("test-retriever", FakeRetriever(["Chunk 1", "Chunk 2"]))

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
        registry.register("test-retriever", FakeRetriever(["Should not appear"]))

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
        registry.register("bad-retriever", FailingRetriever())

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]
        # Should not raise
        prompt = await assemble_system_prompt(
            agent, state, query="hello", retriever_registry=registry
        )

        assert "Retrieved Context" not in prompt
        assert "Instructions" in prompt

    async def test_slow_retriever_times_out(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - slow\n---\n# Agent\n\nInstructions."
        )

        registry = RetrieverRegistry()
        registry.register("slow", _SlowRetriever())

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]

        cfg = ContextRetrievalConfig(retriever_timeout_seconds=0.1)
        prompt = await assemble_system_prompt(
            agent,
            state,
            query="hello",
            retriever_registry=registry,
            context_retrieval_config=cfg,
        )

        assert "should not appear" not in prompt
        assert "Retrieved Context" not in prompt
        assert "Instructions" in prompt

    async def test_retrievers_run_concurrently(self, tmp_path: Path) -> None:
        """Multiple retrievers should run in parallel, not sequentially."""
        import time

        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - r1\n  - r2\n  - r3\n---\n# Agent\n\nInstructions."
        )

        class _DelayedRetriever:
            def __init__(self, name: str, delay: float = 0.1) -> None:
                self._name = name
                self._delay = delay

            async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
                await asyncio.sleep(self._delay)
                return [f"from-{self._name}"]

            async def initialize(self) -> None:
                pass

            async def close(self) -> None:
                pass

        registry = RetrieverRegistry()
        registry.register("r1", _DelayedRetriever("r1", 0.1))
        registry.register("r2", _DelayedRetriever("r2", 0.1))
        registry.register("r3", _DelayedRetriever("r3", 0.1))

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]

        start = time.monotonic()
        prompt = await assemble_system_prompt(
            agent, state, query="hello", retriever_registry=registry
        )
        elapsed = time.monotonic() - start

        # If sequential, would take ~0.3s. Concurrent should be ~0.1s.
        assert elapsed < 0.25, f"Retrievers appear sequential: took {elapsed:.2f}s"
        assert "from-r1" in prompt
        assert "from-r2" in prompt
        assert "from-r3" in prompt

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


class TestContextSizeLimits:
    async def test_retriever_output_truncated(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - big\n---\n# Agent\n\nInstructions."
        )

        registry = RetrieverRegistry()
        registry.register("big", FakeRetriever(["A" * 500, "B" * 500, "C" * 500]))

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]

        cfg = ContextRetrievalConfig(max_retrieved_chars=800)
        prompt = await assemble_system_prompt(
            agent,
            state,
            query="hello",
            retriever_registry=registry,
            context_retrieval_config=cfg,
        )

        # First chunk (500) fits, second (500) would exceed 800, so truncated
        assert "A" * 500 in prompt
        assert "B" * 500 not in prompt

    async def test_static_context_file_truncated(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nInstructions.")
        (context_dir / "big.md").write_text("X" * 2000)

        state = load_workspace(tmp_path)
        agent = state.agents["my-agent"]

        cfg = ContextRetrievalConfig(max_context_file_chars=500)
        prompt = await assemble_system_prompt(agent, state, context_retrieval_config=cfg)

        assert "Reference Material" in prompt
        # Content should be truncated to 500 chars
        assert "X" * 500 in prompt
        assert "X" * 501 not in prompt


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
