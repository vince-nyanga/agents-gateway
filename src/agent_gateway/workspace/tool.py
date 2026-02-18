"""Tool model — loaded from TOOL.md."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_gateway.workspace.parser import parse_markdown_file

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """A single tool parameter."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: list[str] | None = None
    default: Any = None


@dataclass
class ToolDefinition:
    """A fully parsed file-based tool definition."""

    id: str  # Directory name
    path: Path  # Directory path
    name: str  # From frontmatter
    description: str  # From frontmatter
    parameters: list[ToolParameter] = field(default_factory=list)
    instructions: str = ""  # Markdown body
    handler_path: Path | None = None  # Path to handler.py
    permissions: dict[str, Any] = field(default_factory=dict)

    def to_json_schema(self) -> dict[str, Any]:
        """Convert parameters to JSON Schema object."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            prop: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.enum is not None:
                prop["enum"] = param.enum
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def to_llm_declaration(self) -> dict[str, Any]:
        """Convert to LLM function-calling tool declaration."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.to_json_schema(),
            },
        }

    @classmethod
    def load(cls, tool_dir: Path) -> ToolDefinition | None:
        """Load a tool from a directory. Returns None if TOOL.md missing."""
        tool_md = tool_dir / "TOOL.md"
        if not tool_md.exists():
            return None

        parsed = parse_markdown_file(tool_md)
        meta = parsed.metadata

        name = meta.get("name", tool_dir.name)
        description = meta.get("description", "")

        if not description:
            logger.warning("Tool %s has no description", tool_dir.name)

        # Parse parameters
        params_data = meta.get("parameters", {})
        parameters = []
        for param_name, param_def in params_data.items():
            if isinstance(param_def, dict):
                parameters.append(
                    ToolParameter(
                        name=param_name,
                        type=param_def.get("type", "string"),
                        description=param_def.get("description", param_name),
                        required=param_def.get("required", False),
                        enum=param_def.get("enum"),
                        default=param_def.get("default"),
                    )
                )

        # Parse permissions
        perms_data = meta.get("permissions", {})
        permissions: dict[str, Any] = {}
        if isinstance(perms_data, dict):
            if "allowed_agents" in perms_data:
                permissions["allowed_agents"] = perms_data["allowed_agents"]
            if "require_approval" in perms_data:
                permissions["require_approval"] = bool(perms_data["require_approval"])

        # Check for handler.py
        handler_path = tool_dir / "handler.py"
        has_handler = handler_path.exists()

        return cls(
            id=tool_dir.name,
            path=tool_dir,
            name=name,
            description=description,
            parameters=parameters,
            instructions=parsed.content,
            handler_path=handler_path if has_handler else None,
            permissions=permissions,
        )
