"""Runtime domain types for MCP integration (not persisted)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MCP_TOOL_SEPARATOR: str = "__"
"""Hard-coded separator for namespacing MCP tools: {server_name}__{tool_name}."""


@dataclass
class McpToolInfo:
    """A tool discovered from an MCP server (runtime only, not persisted)."""

    server_name: str
    name: str  # original MCP tool name
    description: str
    input_schema: dict[str, Any]

    @property
    def namespaced_name(self) -> str:
        return f"{self.server_name}{MCP_TOOL_SEPARATOR}{self.name}"


@dataclass
class McpToolRef:
    """Reference stored on ResolvedTool for MCP tool dispatch (runtime only)."""

    server_name: str
    tool_name: str  # original (un-namespaced) name
