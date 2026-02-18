---
title: "Phase 1.3: Tool Registry & @gw.tool Decorator"
type: feat
status: completed
date: 2026-02-18
depends_on: [01, 02]
blocks: [04, 05, 08]
parent: 2026-02-18-feat-agent-gateway-framework-plan.md
---

# Phase 1.3: Tool Registry & @gw.tool Decorator

## Goal

Build the unified tool registry that merges file-based tools (TOOL.md) with code-based tools (`@gw.tool()`). Implement the `@gw.tool` decorator with all 4 input spec modes (Annotated, Pydantic, explicit dict, bare hints). After this phase, tools can be registered from both sources, resolved per-agent (with permission checks), and converted to LLM function declarations.

## Prerequisites

- Phase 01 (package structure)
- Phase 02 (workspace loader, ToolDefinition model)

---

## Tasks

### 1. Tool Schema Generator

**File:** `src/agent_gateway/workspace/schema.py`

Generates JSON Schema from Python function signatures. Supports 4 modes:

1. **Explicit `parameters` dict** — used as-is, no inference
2. **Pydantic model as sole parameter** — `model.model_json_schema()`
3. **`Annotated[type, "description"]` parameters** — type + description extracted
4. **Bare type hints** — type inferred, parameter name used as description

```python
"""Generate JSON Schema from Python function signatures for LLM tool declarations."""

from __future__ import annotations

import inspect
from typing import Annotated, Any, Literal, get_args, get_origin, get_type_hints

from pydantic import BaseModel


# Python type → JSON Schema type mapping
TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def schema_from_function(fn: Any) -> dict[str, Any]:
    """Generate JSON Schema parameters from a function's type hints."""
    hints = get_type_hints(fn, include_extras=True)
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls", "return"):
            continue

        hint = hints.get(name, str)

        # Check if single Pydantic model parameter
        if inspect.isclass(hint) and issubclass(hint, BaseModel):
            return hint.model_json_schema()

        prop = _hint_to_schema(hint, name)
        properties[name] = prop

        # Required if no default
        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _hint_to_schema(hint: Any, name: str) -> dict[str, Any]:
    """Convert a single type hint to a JSON Schema property."""
    origin = get_origin(hint)
    args = get_args(hint)

    # Annotated[type, "description"]
    if origin is Annotated:
        base_type = args[0]
        description = next((a for a in args[1:] if isinstance(a, str)), name)
        prop = _base_type_to_schema(base_type)
        prop["description"] = description
        return prop

    # Optional[X] → X (not required, handled by caller)
    if origin is type(None):
        return {"type": "string", "description": name}

    # Literal["A", "B"] → enum
    if origin is Literal:
        return {"type": "string", "enum": list(args), "description": name}

    # list[X]
    if origin is list and args:
        item_schema = _base_type_to_schema(args[0])
        return {"type": "array", "items": item_schema, "description": name}

    # Plain type
    prop = _base_type_to_schema(hint)
    prop["description"] = name
    return prop


def _base_type_to_schema(t: Any) -> dict[str, Any]:
    """Map a Python type to JSON Schema."""
    json_type = TYPE_MAP.get(t, "string")
    return {"type": json_type}
```

### 2. Tool Registry

**File:** `src/agent_gateway/workspace/registry.py`

```python
"""Unified tool registry — merges file-based and code-based tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from agent_gateway.workspace.tool import ToolDefinition

logger = logging.getLogger(__name__)


@dataclass
class CodeTool:
    """A tool registered via @gw.tool()."""
    name: str
    description: str
    fn: Callable[..., Any]
    parameters_schema: dict[str, Any]
    allowed_agents: list[str] | None = None    # None = all agents
    require_approval: bool = False

    def to_llm_declaration(self) -> dict[str, Any]:
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
    source: str                                # "file" or "code"
    llm_declaration: dict[str, Any]
    parameters_schema: dict[str, Any]
    allowed_agents: list[str] | None = None
    require_approval: bool = False
    # File tool fields
    file_tool: ToolDefinition | None = None
    # Code tool fields
    code_tool: CodeTool | None = None

    def allows_agent(self, agent_id: str) -> bool:
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
        self._file_tools[tool.name] = tool
        self._resolved = None  # Invalidate cache

    def register_file_tools(self, tools: dict[str, ToolDefinition]) -> None:
        for tool in tools.values():
            self.register_file_tool(tool)

    def register_code_tool(self, tool: CodeTool) -> None:
        if tool.name in self._file_tools:
            logger.info("Code tool '%s' overrides file-based tool", tool.name)
        self._code_tools[tool.name] = tool
        self._resolved = None

    def get(self, name: str) -> ResolvedTool | None:
        resolved = self._resolve_all()
        return resolved.get(name)

    def get_all(self) -> dict[str, ResolvedTool]:
        return self._resolve_all()

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

        for name in needed_names:
            if name in seen:
                continue
            seen.add(name)
            tool = all_resolved.get(name)
            if tool is None:
                logger.warning("Tool '%s' not found for agent '%s'", name, agent_id)
                continue
            if not tool.allows_agent(agent_id):
                logger.warning(
                    "Tool '%s' not permitted for agent '%s'", name, agent_id
                )
                continue
            result.append(tool)

        return result

    def to_llm_declarations(self, tools: list[ResolvedTool]) -> list[dict[str, Any]]:
        return [t.llm_declaration for t in tools]

    def _resolve_all(self) -> dict[str, ResolvedTool]:
        if self._resolved is not None:
            return self._resolved

        resolved: dict[str, ResolvedTool] = {}

        # File tools first
        for tool in self._file_tools.values():
            perms = tool.permissions
            resolved[tool.name] = ResolvedTool(
                name=tool.name,
                description=tool.description,
                source="file",
                llm_declaration=tool.to_llm_declaration(),
                parameters_schema=tool.to_json_schema(),
                allowed_agents=perms.get("allowed_agents"),
                require_approval=perms.get("require_approval", False),
                file_tool=tool,
            )

        # Code tools override file tools
        for tool in self._code_tools.values():
            resolved[tool.name] = ResolvedTool(
                name=tool.name,
                description=tool.description,
                source="code",
                llm_declaration=tool.to_llm_declaration(),
                parameters_schema=tool.parameters_schema,
                allowed_agents=tool.allowed_agents,
                require_approval=tool.require_approval,
                code_tool=tool,
            )

        self._resolved = resolved
        return resolved
```

### 3. `@gw.tool()` Decorator

Add to `src/agent_gateway/gateway.py`:

```python
def tool(
    self,
    fn: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
    allowed_agents: list[str] | None = None,
    require_approval: bool = False,
) -> Callable:
    """Register a tool. Can be used as @gw.tool or @gw.tool()."""
    from agent_gateway.workspace.registry import CodeTool
    from agent_gateway.workspace.schema import schema_from_function

    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__.replace("_", "-")
        tool_desc = description or func.__doc__ or ""

        if parameters is not None:
            params_schema = parameters
        else:
            params_schema = schema_from_function(func)

        code_tool = CodeTool(
            name=tool_name,
            description=tool_desc.strip(),
            fn=func,
            parameters_schema=params_schema,
            allowed_agents=allowed_agents,
            require_approval=require_approval,
        )

        if not hasattr(self, "_pending_tools"):
            self._pending_tools: list[CodeTool] = []
        self._pending_tools.append(code_tool)

        return func

    if fn is not None:
        return decorator(fn)
    return decorator
```

---

## Tests

- Schema generation: all 4 modes (Annotated, Pydantic, explicit, bare)
- Type mapping: str, int, float, bool, list, dict, list[str], Optional, Literal
- Registry: register file + code tools, code overrides file, resolve per agent
- Permission checks: allowed_agents filtering
- LLM declaration generation
- Decorator: `@gw.tool`, `@gw.tool()`, with all parameters

## Acceptance Criteria

- [x] `@gw.tool` decorator works in all 4 modes
- [x] `ToolRegistry` merges file and code tools correctly
- [x] Code tools override file tools with same name
- [x] `resolve_for_agent()` filters by permissions
- [x] `to_llm_declarations()` produces correct format
- [x] All tests pass
