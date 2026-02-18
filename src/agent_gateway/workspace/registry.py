"""Unified tool registry — merges file-based and code-based tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_gateway.workspace.tool import ToolDefinition

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
    """A tool ready for execution — unified interface for file and code tools."""

    name: str
    description: str
    source: str  # "file" or "code"
    llm_declaration: dict[str, Any]
    parameters_schema: dict[str, Any]
    allowed_agents: list[str] | None = None
    require_approval: bool = False
    # File tool fields
    file_tool: ToolDefinition | None = None
    # Code tool fields
    code_tool: CodeTool | None = None

    def allows_agent(self, agent_id: str) -> bool:
        """Check if the tool is available to the given agent."""
        if self.allowed_agents is None:
            return True
        return agent_id in self.allowed_agents


class ToolRegistry:
    """Manages all tools — file-based and code-based."""

    def __init__(self) -> None:
        self._file_tools: dict[str, ToolDefinition] = {}
        self._code_tools: dict[str, CodeTool] = {}
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
        skill_tool_names: list[str],
        direct_tool_names: list[str],
    ) -> list[ResolvedTool]:
        """Resolve all tools available to an agent (from skills + direct tools).

        Deduplicates by name. Checks allowed_agents permissions.
        """
        all_resolved = self._resolve_all()
        needed_names = set(skill_tool_names) | set(direct_tool_names)
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
        """Merge file and code tools into resolved tools. Cached."""
        if self._resolved is not None:
            return self._resolved

        resolved: dict[str, ResolvedTool] = {}

        # File tools first
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

        # Code tools override file tools
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
