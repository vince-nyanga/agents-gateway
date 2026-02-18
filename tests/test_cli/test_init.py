"""Tests for agent-gateway init command."""

from __future__ import annotations

from typer.testing import CliRunner

from agent_gateway.cli.main import app

runner = CliRunner()


def test_init_creates_project(tmp_path: object, monkeypatch) -> None:
    """init creates the expected directory structure."""
    import pathlib

    work_dir = pathlib.Path(str(tmp_path))
    monkeypatch.chdir(work_dir)

    result = runner.invoke(app, ["init", "my-project"])
    assert result.exit_code == 0
    assert "Created project 'my-project'" in result.output

    project = work_dir / "my-project"
    assert project.is_dir()
    assert (project / "app.py").exists()
    assert (project / ".env.example").exists()
    assert (project / ".gitignore").exists()
    assert (project / "workspace" / "gateway.yaml").exists()
    assert (project / "workspace" / "agents" / "assistant" / "AGENT.md").exists()
    assert (project / "workspace" / "agents" / "assistant" / "SOUL.md").exists()
    assert (project / "workspace" / "skills").is_dir()
    assert (project / "workspace" / "tools").is_dir()


def test_init_app_py_content(tmp_path: object, monkeypatch) -> None:
    """init creates app.py with correct import."""
    import pathlib

    work_dir = pathlib.Path(str(tmp_path))
    monkeypatch.chdir(work_dir)

    runner.invoke(app, ["init", "test-proj"])
    content = (work_dir / "test-proj" / "app.py").read_text()
    assert "from agent_gateway import Gateway" in content
    assert 'gw = Gateway(workspace="./workspace")' in content


def test_init_fails_if_dir_exists(tmp_path: object, monkeypatch) -> None:
    """init errors if directory already exists."""
    import pathlib

    work_dir = pathlib.Path(str(tmp_path))
    monkeypatch.chdir(work_dir)
    (work_dir / "existing").mkdir()

    result = runner.invoke(app, ["init", "existing"])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_init_next_steps(tmp_path: object, monkeypatch) -> None:
    """init prints next steps."""
    import pathlib

    work_dir = pathlib.Path(str(tmp_path))
    monkeypatch.chdir(work_dir)

    result = runner.invoke(app, ["init", "demo"])
    assert "cd demo" in result.output
    assert "pip install agent-gateway" in result.output
