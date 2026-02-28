"""Unified tool registry — merges file-based, code-based, and MCP tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from agent_gateway.workspace.tool import ToolDefinition

if TYPE_CHECKING:
    from agent_gateway.mcp.domain import McpToolRef

logger = logging.getLogger(__name__)


@dataclass
class CodeTool:
    """A tool registered via @gw.tool()."""

    name: str
    description: str
    fn: Callable[..., Any]
    parameters_schema: dict[str, Any]
    allowed_agents: list[str] | None = None  # None = all agents
    require_approval: bool = False

    def to_llm_declaration(self) -> dict[str, Any]:
        """Convert to LLM function-calling tool declaration."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


@dataclass
class ResolvedTool:
    """A tool ready for execution — unified interface for file, code, and MCP tools."""

    name: str
    description: str
    source: Literal["file", "code", "mcp"]
    llm_declaration: dict[str, Any]
    parameters_schema: dict[str, Any]
    allowed_agents: list[str] | None = None
    require_approval: bool = False
    # File tool fields
    file_tool: ToolDefinition | None = None
    # Code tool fields
    code_tool: CodeTool | None = None
    # MCP tool fields
    mcp_tool: McpToolRef | None = None  # set when source="mcp"

    def allows_agent(self, agent_id: str) -> bool:
        """Check if the tool is available to the given agent."""
        if self.allowed_agents is None:
            return True
        return agent_id in self.allowed_agents


class ToolRegistry:
    """Manages all tools — file-based, code-based, and MCP."""

    def __init__(self) -> None:
        self._file_tools: dict[str, ToolDefinition] = {}
        self._code_tools: dict[str, CodeTool] = {}
        self._mcp_tools: dict[str, ResolvedTool] = {}
        self._resolved: dict[str, ResolvedTool] | None = None

    def register_file_tool(self, tool: ToolDefinition) -> None:
        """Register a tool loaded from TOOL.md."""
        self._file_tools[tool.name] = tool
        self._resolved = None  # Invalidate cache

    def register_file_tools(self, tools: dict[str, ToolDefinition]) -> None:
        """Register multiple file-based tools."""
        for tool in tools.values():
            self.register_file_tool(tool)

    def register_code_tool(self, tool: CodeTool) -> None:
        """Register a tool from @gw.tool(). Code tools override file tools."""
        if tool.name in self._file_tools:
            logger.info("Code tool '%s' overrides file-based tool", tool.name)
        self._code_tools[tool.name] = tool
        self._resolved = None

    def register_mcp_tools(
        self,
        tools: list[Any],
        allowed_agents: list[str] | None = None,
    ) -> None:
        """Register tools discovered from MCP servers.

        Args:
            tools: Discovered MCP tools (McpToolInfo instances).
            allowed_agents: Agent IDs permitted to use these tools.
                If None, tools are available to all agents (not recommended).
        """
        from agent_gateway.mcp.domain import McpToolRef

        for tool in tools:
            ns_name = tool.namespaced_name
            if ns_name in self._mcp_tools:
                logger.warning(
                    "MCP tool '%s' already registered; overwriting with new definition",
                    ns_name,
                )
            resolved = ResolvedTool(
                name=ns_name,
                description=tool.description,
                source="mcp",
                llm_declaration={
                    "type": "function",
                    "function": {
                        "name": ns_name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                },
                parameters_schema=tool.input_schema,
                allowed_agents=allowed_agents,
                mcp_tool=McpToolRef(
                    server_name=tool.server_name,
                    tool_name=tool.name,
                ),
            )
            self._mcp_tools[ns_name] = resolved
        self._resolved = None  # invalidate cache

    def clear_mcp_tools(self, server_name: str | None = None) -> None:
        """Remove MCP tools, optionally filtered by server name.

        Args:
            server_name: If provided, only remove tools from this server.
                If None, removes all MCP tools.
        """
        if server_name is None:
            self._mcp_tools.clear()
        else:
            to_remove = [
                name
                for name, rt in self._mcp_tools.items()
                if rt.mcp_tool is not None and rt.mcp_tool.server_name == server_name
            ]
            for name in to_remove:
                del self._mcp_tools[name]
        self._resolved = None

    def get(self, name: str) -> ResolvedTool | None:
        """Get a resolved tool by name."""
        resolved = self._resolve_all()
        return resolved.get(name)

    def get_all(self) -> dict[str, ResolvedTool]:
        """Get all resolved tools."""
        return dict(self._resolve_all())

    def resolve_for_agent(
        self,
        agent_id: str,
        tool_names: list[str],
    ) -> list[ResolvedTool]:
        """Resolve all tools available to an agent (from skills).

        Agents gain tools exclusively through their skills.
        Deduplicates by name. Checks allowed_agents permissions.
        """
        all_resolved = self._resolve_all()
        needed_names = set(tool_names)
        result: list[ResolvedTool] = []
        seen: set[str] = set()

        for name in sorted(needed_names):  # Sort for deterministic order
            if name in seen:
                continue
            seen.add(name)
            tool = all_resolved.get(name)
            if tool is None:
                logger.warning("Tool '%s' not found for agent '%s'", name, agent_id)
                continue
            if not tool.allows_agent(agent_id):
                logger.warning("Tool '%s' not permitted for agent '%s'", name, agent_id)
                continue
            result.append(tool)

        return result

    def to_llm_declarations(self, tools: list[ResolvedTool]) -> list[dict[str, Any]]:
        """Convert resolved tools to LLM function declarations."""
        return [t.llm_declaration for t in tools]

    def _resolve_all(self) -> dict[str, ResolvedTool]:
        """Merge MCP, file, and code tools into resolved tools. Cached."""
        if self._resolved is not None:
            return self._resolved

        resolved: dict[str, ResolvedTool] = {}

        # MCP tools first (lowest priority -- overridden by file and code tools)
        for mt in self._mcp_tools.values():
            resolved[mt.name] = mt

        # File tools override MCP tools
        for ft in self._file_tools.values():
            perms = ft.permissions
            resolved[ft.name] = ResolvedTool(
                name=ft.name,
                description=ft.description,
                source="file",
                llm_declaration=ft.to_llm_declaration(),
                parameters_schema=ft.to_json_schema(),
                allowed_agents=perms.get("allowed_agents"),
                require_approval=perms.get("require_approval", False),
                file_tool=ft,
            )

        # Code tools override both file and MCP tools
        for ct in self._code_tools.values():
            resolved[ct.name] = ResolvedTool(
                name=ct.name,
                description=ct.description,
                source="code",
                llm_declaration=ct.to_llm_declaration(),
                parameters_schema=ct.parameters_schema,
                allowed_agents=ct.allowed_agents,
                require_approval=ct.require_approval,
                code_tool=ct,
            )

        self._resolved = resolved
        return resolved
