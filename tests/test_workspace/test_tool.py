"""Tests for tool model loading."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.workspace.tool import ToolDefinition


class TestToolDefinition:
    def test_load_tool(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "echo"
        tool_dir.mkdir()
        (tool_dir / "TOOL.md").write_text(
            "---\n"
            "name: echo\n"
            "description: Echo the input back\n"
            "parameters:\n"
            "  message:\n"
            "    type: string\n"
            "    description: Message to echo\n"
            "    required: true\n"
            "---\n"
            "# Echo Tool\n\nReturns input unchanged."
        )

        tool = ToolDefinition.load(tool_dir)
        assert tool is not None
        assert tool.id == "echo"
        assert tool.name == "echo"
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "message"
        assert tool.parameters[0].required is True
        assert tool.handler_path is None  # No handler.py

    def test_load_tool_with_handler(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "compute"
        tool_dir.mkdir()
        (tool_dir / "TOOL.md").write_text(
            "---\nname: compute\ndescription: Compute things\n---\n# Compute"
        )
        (tool_dir / "handler.py").write_text("def handle(args, context): return args")

        tool = ToolDefinition.load(tool_dir)
        assert tool is not None
        assert tool.handler_path == tool_dir / "handler.py"

    def test_missing_tool_md_returns_none(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "no-tool"
        tool_dir.mkdir()
        assert ToolDefinition.load(tool_dir) is None

    def test_parameter_with_enum(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "choice"
        tool_dir.mkdir()
        (tool_dir / "TOOL.md").write_text(
            "---\n"
            "name: choice\n"
            "description: Pick one\n"
            "parameters:\n"
            "  color:\n"
            "    type: string\n"
            "    description: Pick a color\n"
            "    enum:\n      - red\n      - blue\n      - green\n"
            "---\n# Choice"
        )

        tool = ToolDefinition.load(tool_dir)
        assert tool is not None
        assert tool.parameters[0].enum == ["red", "blue", "green"]

    def test_parameter_with_default(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "default-param"
        tool_dir.mkdir()
        (tool_dir / "TOOL.md").write_text(
            "---\n"
            "name: default-param\n"
            "description: Has default\n"
            "parameters:\n"
            "  count:\n"
            "    type: integer\n"
            "    description: Number of items\n"
            "    default: 10\n"
            "---\n# Default"
        )

        tool = ToolDefinition.load(tool_dir)
        assert tool is not None
        assert tool.parameters[0].default == 10

    def test_permissions(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "restricted"
        tool_dir.mkdir()
        (tool_dir / "TOOL.md").write_text(
            "---\n"
            "name: restricted\n"
            "description: Restricted tool\n"
            "permissions:\n"
            "  allowed_agents:\n"
            "    - agent-a\n"
            "  require_approval: true\n"
            "---\n# Restricted"
        )

        tool = ToolDefinition.load(tool_dir)
        assert tool is not None
        assert tool.permissions["allowed_agents"] == ["agent-a"]
        assert tool.permissions["require_approval"] is True

    def test_to_json_schema(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "schema-test"
        tool_dir.mkdir()
        (tool_dir / "TOOL.md").write_text(
            "---\n"
            "name: schema-test\n"
            "description: Schema test\n"
            "parameters:\n"
            "  name:\n"
            "    type: string\n"
            "    description: Your name\n"
            "    required: true\n"
            "  age:\n"
            "    type: integer\n"
            "    description: Your age\n"
            "---\n# Schema Test"
        )

        tool = ToolDefinition.load(tool_dir)
        assert tool is not None
        schema = tool.to_json_schema()
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]
        assert schema["required"] == ["name"]

    def test_to_llm_declaration(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "decl-test"
        tool_dir.mkdir()
        (tool_dir / "TOOL.md").write_text(
            "---\nname: decl-test\ndescription: Declaration test\n---\n# Decl"
        )

        tool = ToolDefinition.load(tool_dir)
        assert tool is not None
        decl = tool.to_llm_declaration()
        assert decl["type"] == "function"
        assert decl["function"]["name"] == "decl-test"
        assert decl["function"]["description"] == "Declaration test"
