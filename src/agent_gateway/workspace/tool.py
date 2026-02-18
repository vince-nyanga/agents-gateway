"""Tool model — loaded from TOOL.md."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agent_gateway.workspace.parser import parse_markdown_file

logger = logging.getLogger(__name__)

ToolType = Literal["http", "function", "script"]
VALID_TOOL_TYPES: set[str] = {"http", "function", "script"}


@dataclass
class HttpConfig:
    """HTTP tool configuration."""

    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    timeout_ms: int = 15_000


@dataclass
class ScriptConfig:
    """Script tool configuration."""

    command: str = ""
    timeout_ms: int = 30_000


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
    type: ToolType = "function"
    parameters: list[ToolParameter] = field(default_factory=list)
    http: HttpConfig | None = None
    script: ScriptConfig | None = None
    instructions: str = ""  # Markdown body
    handler_path: Path | None = None  # Path to handler.py (for function tools)
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
        tool_type = meta.get("type", "function")

        if not description:
            logger.warning("Tool %s has no description", tool_dir.name)

        if tool_type not in VALID_TOOL_TYPES:
            logger.warning(
                "Tool %s has unknown type '%s', defaulting to 'function'",
                tool_dir.name,
                tool_type,
            )
            tool_type = "function"

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

        # Parse HTTP config
        http_config = None
        if tool_type == "http":
            http_data = meta.get("http", {})
            http_config = HttpConfig(
                method=http_data.get("method", "GET"),
                url=http_data.get("url", ""),
                headers=http_data.get("headers", {}),
                body=http_data.get("body"),
                timeout_ms=http_data.get("timeout_ms", 15_000),
            )

        # Parse script config
        script_config = None
        if tool_type == "script":
            script_data = meta.get("script", {})
            script_config = ScriptConfig(
                command=script_data.get("command", ""),
                timeout_ms=script_data.get("timeout_ms", 30_000),
            )

        # Parse permissions
        perms_data = meta.get("permissions", {})
        permissions: dict[str, Any] = {}
        if isinstance(perms_data, dict):
            if "allowed_agents" in perms_data:
                permissions["allowed_agents"] = perms_data["allowed_agents"]
            if "require_approval" in perms_data:
                permissions["require_approval"] = bool(perms_data["require_approval"])

        # Check for handler.py (function tools)
        handler_path = tool_dir / "handler.py"
        has_handler = handler_path.exists() if tool_type == "function" else False

        return cls(
            id=tool_dir.name,
            path=tool_dir,
            name=name,
            description=description,
            type=tool_type,
            parameters=parameters,
            http=http_config,
            script=script_config,
            instructions=parsed.content,
            handler_path=handler_path if has_handler else None,
            permissions=permissions,
        )
