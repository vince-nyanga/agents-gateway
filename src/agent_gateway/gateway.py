"""Gateway - FastAPI subclass for AI agent services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, overload

from fastapi import FastAPI

from agent_gateway.workspace.registry import CodeTool


class Gateway(FastAPI):
    """An opinionated FastAPI extension for building API-first AI agent services.

    Subclasses FastAPI directly. Everything you can do with a FastAPI app,
    you can do with a Gateway.
    """

    def __init__(
        self,
        workspace: str = "./workspace",
        auth: bool | None = True,
        reload: bool = False,
        **fastapi_kwargs: Any,
    ) -> None:
        self._workspace_path = workspace
        self._auth_enabled = auth
        self._reload_enabled = reload
        self._pending_tools: list[CodeTool] = []
        super().__init__(**fastapi_kwargs)

    @overload
    def tool(self, fn: Callable[..., Any]) -> Callable[..., Any]: ...

    @overload
    def tool(
        self,
        fn: None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        parameters: dict[str, Any] | None = None,
        allowed_agents: list[str] | None = None,
        require_approval: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

    def tool(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        parameters: dict[str, Any] | None = None,
        allowed_agents: list[str] | None = None,
        require_approval: bool = False,
    ) -> Callable[..., Any] | Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a tool. Can be used as @gw.tool or @gw.tool().

        Supports 4 input spec modes:
        1. Explicit ``parameters`` dict — used as-is, no inference.
        2. Single Pydantic model parameter — schema from model_json_schema().
        3. ``Annotated[type, "description"]`` — type + description extracted.
        4. Bare type hints — type inferred, parameter name used as description.
        """
        from agent_gateway.workspace.schema import schema_from_function

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__.replace("_", "-")
            tool_desc = description or func.__doc__ or ""

            params_schema = parameters if parameters is not None else schema_from_function(func)

            code_tool = CodeTool(
                name=tool_name,
                description=tool_desc.strip(),
                fn=func,
                parameters_schema=params_schema,
                allowed_agents=allowed_agents,
                require_approval=require_approval,
            )

            self._pending_tools.append(code_tool)
            return func

        if fn is not None:
            return decorator(fn)
        return decorator

    def run(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        **kwargs: object,
    ) -> None:
        """Start the gateway server using uvicorn."""
        import uvicorn

        uvicorn.run(self, host=host, port=port, **kwargs)  # type: ignore[arg-type]
