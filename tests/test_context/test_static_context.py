"""Tests for static context file loading in AgentDefinition."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.agent import AgentDefinition


class TestStaticContextAutoDiscovery:
    def test_loads_md_files_from_context_dir(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nHello.")
        (context_dir / "01-tone.md").write_text("Be formal.")
        (context_dir / "02-examples.md").write_text("Example email.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert len(agent.context_content) == 2
        assert "Be formal." in agent.context_content[0]
        assert "Example email." in agent.context_content[1]

    def test_alphabetical_order(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nHello.")
        (context_dir / "b-second.md").write_text("B")
        (context_dir / "a-first.md").write_text("A")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.context_content == ["A", "B"]

    def test_non_md_files_ignored(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nHello.")
        (context_dir / "data.json").write_text('{"key": "value"}')
        (context_dir / "notes.txt").write_text("some notes")
        (context_dir / "guide.md").write_text("Guide content.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert len(agent.context_content) == 1
        assert "Guide content." in agent.context_content[0]

    def test_no_context_dir(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nHello.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.context_content == []

    def test_empty_context_dir(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nHello.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.context_content == []

    def test_symlink_in_context_dir_skipped(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nHello.")
        (context_dir / "real.md").write_text("Real content.")

        # Create a symlink
        target = tmp_path / "secret.md"
        target.write_text("Secret!")
        symlink = context_dir / "link.md"
        symlink.symlink_to(target)

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert len(agent.context_content) == 1
        assert "Real content." in agent.context_content[0]


class TestStaticContextExplicitPaths:
    def test_explicit_context_paths(self, tmp_path: Path) -> None:
        # workspace root is tmp_path (grandparent of agent dir)
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        (shared_dir / "style-guide.md").write_text("Use active voice.")

        (agent_dir / "AGENT.md").write_text(
            "---\ncontext:\n  - shared/style-guide.md\n---\n# Agent\n\nHello."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert len(agent.context_content) == 1
        assert "Use active voice." in agent.context_content[0]

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\ncontext:\n  - ../../../etc/passwd\n---\n# Agent\n\nHello."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.context_content == []

    def test_missing_explicit_file_warned(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\ncontext:\n  - shared/nonexistent.md\n---\n# Agent\n\nHello."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.context_content == []

    def test_combined_auto_and_explicit(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        context_dir = agent_dir / "context"
        context_dir.mkdir(parents=True)
        (context_dir / "auto.md").write_text("Auto content.")

        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        (shared_dir / "explicit.md").write_text("Explicit content.")

        (agent_dir / "AGENT.md").write_text(
            "---\ncontext:\n  - shared/explicit.md\n---\n# Agent\n\nHello."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert len(agent.context_content) == 2
        assert "Auto content." in agent.context_content[0]
        assert "Explicit content." in agent.context_content[1]

    def test_invalid_context_type_ignored(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("---\ncontext: not-a-list\n---\n# Agent\n\nHello.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.context_content == []


class TestRetrieversParsing:
    def test_retriever_names_parsed(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "---\nretrievers:\n  - vector-search\n  - web-search\n---\n# Agent\n\nHello."
        )

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.retrievers == ["vector-search", "web-search"]

    def test_no_retrievers(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("# Agent\n\nHello.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.retrievers == []

    def test_invalid_retrievers_ignored(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "my-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("---\nretrievers: not-a-list\n---\n# Agent\n\nHello.")

        agent = AgentDefinition.load(agent_dir)
        assert agent is not None
        assert agent.retrievers == []
