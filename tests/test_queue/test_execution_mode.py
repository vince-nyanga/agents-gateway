"""Tests for execution_mode parsing from agent frontmatter."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.agent import AgentDefinition


def _write_agent(tmp_path: Path, frontmatter: str, body: str = "You are a test agent.") -> Path:
    """Create an agent directory with AGENT.md."""
    agent_dir = tmp_path / "test-agent"
    agent_dir.mkdir(exist_ok=True)
    (agent_dir / "AGENT.md").write_text(f"---\n{frontmatter}\n---\n{body}")
    return agent_dir


def test_execution_mode_default_is_sync(tmp_path: Path) -> None:
    """Without execution_mode in frontmatter, default is sync."""
    agent_dir = _write_agent(tmp_path, "skills:\n  - test")
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert agent.execution_mode == "sync"


def test_execution_mode_async_from_agent_md(tmp_path: Path) -> None:
    """execution_mode: async parsed from AGENT.md frontmatter."""
    agent_dir = _write_agent(tmp_path, "execution_mode: async")
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert agent.execution_mode == "async"


def test_execution_mode_sync_explicit(tmp_path: Path) -> None:
    """execution_mode: sync is explicitly set."""
    agent_dir = _write_agent(tmp_path, "execution_mode: sync")
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert agent.execution_mode == "sync"


def test_execution_mode_config_md_overrides_agent_md(tmp_path: Path) -> None:
    """CONFIG.md execution_mode overrides AGENT.md."""
    agent_dir = _write_agent(tmp_path, "execution_mode: sync")
    (agent_dir / "CONFIG.md").write_text("---\nexecution_mode: async\n---\n")
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert agent.execution_mode == "async"


def test_execution_mode_invalid_falls_back_to_sync(tmp_path: Path) -> None:
    """Invalid execution_mode value falls back to sync."""
    agent_dir = _write_agent(tmp_path, "execution_mode: invalid_value")
    agent = AgentDefinition.load(agent_dir)
    assert agent is not None
    assert agent.execution_mode == "sync"
