"""Gateway - FastAPI subclass for AI agent services."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, overload

from fastapi import APIRouter, FastAPI

from agent_gateway.config import GatewayConfig
from agent_gateway.engine.executor import ExecutionEngine
from agent_gateway.engine.llm import LLMClient
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
)
from agent_gateway.persistence.null import NullAuditRepository, NullExecutionRepository
from agent_gateway.tools.runner import execute_tool
from agent_gateway.workspace.loader import WorkspaceState, load_workspace
from agent_gateway.workspace.registry import CodeTool, ToolRegistry

logger = logging.getLogger(__name__)


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

        # Initialized during lifespan startup
        self._config: GatewayConfig | None = None
        self._workspace: WorkspaceState | None = None
        self._tool_registry: ToolRegistry | None = None
        self._llm_client: LLMClient | None = None
        self._engine: ExecutionEngine | None = None
        self._db_engine: Any = None
        self._execution_repo: Any = NullExecutionRepository()
        self._audit_repo: Any = NullAuditRepository()
        self._execution_handles: dict[str, ExecutionHandle] = {}
        self._event_hooks: dict[str, list[Callable[..., Any]]] = {}

        # Extract user lifespan before we override it
        user_lifespan = fastapi_kwargs.pop("lifespan", None)
        fastapi_kwargs["lifespan"] = self._make_lifespan(user_lifespan)

        super().__init__(**fastapi_kwargs)

        # Register routes eagerly (they don't depend on workspace state)
        self._register_routes()

    def _make_lifespan(
        self, user_lifespan: Callable[..., Any] | None
    ) -> Callable[[FastAPI], AsyncIterator[None]]:
        """Create a composed lifespan that wraps the user's lifespan."""

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            # === Gateway startup ===
            await self._startup()

            if user_lifespan is not None:
                async with user_lifespan(app):
                    yield
            else:
                yield

            # === Gateway shutdown ===
            await self._shutdown()

        return lifespan

    async def _startup(self) -> None:
        """Initialize all gateway components on startup."""
        ws_path = Path(self._workspace_path)

        # 1. Load config (never crashes)
        try:
            self._config = GatewayConfig.load(ws_path)
        except Exception:
            logger.warning("Failed to load config, using defaults", exc_info=True)
            self._config = GatewayConfig()

        # 2. Setup telemetry (never crashes)
        try:
            from agent_gateway.telemetry import setup_telemetry

            setup_telemetry(self._config.telemetry)
        except Exception:
            logger.warning("Failed to setup telemetry", exc_info=True)

        # 3. Load workspace (never crashes)
        try:
            self._workspace = load_workspace(ws_path)
            if self._workspace.errors:
                for err in self._workspace.errors:
                    logger.warning("Workspace error: %s", err)
        except Exception:
            logger.warning("Failed to load workspace", exc_info=True)
            self._workspace = WorkspaceState(
                path=ws_path,
                agents={},
                skills={},
                tools={},
                schedules=[],
                root_system_prompt="",
                root_soul_prompt="",
                warnings=[],
                errors=["Workspace failed to load"],
            )

        # 4. Build tool registry
        self._tool_registry = ToolRegistry()
        if self._workspace:
            self._tool_registry.register_file_tools(self._workspace.tools)
        for code_tool in self._pending_tools:
            self._tool_registry.register_code_tool(code_tool)

        # 5. Init persistence (graceful fallback)
        if self._config.persistence.enabled:
            try:
                from agent_gateway.persistence.repository import (
                    AuditRepository,
                    ExecutionRepository,
                )
                from agent_gateway.persistence.session import (
                    create_db_engine,
                    create_session_factory,
                    init_db,
                )

                self._db_engine = create_db_engine(self._config.persistence)
                await init_db(self._db_engine)
                session_factory = create_session_factory(self._db_engine)
                self._execution_repo = ExecutionRepository(session_factory)
                self._audit_repo = AuditRepository(session_factory)
            except Exception:
                logger.warning("Failed to init persistence, using null repos", exc_info=True)
                self._execution_repo = NullExecutionRepository()
                self._audit_repo = NullAuditRepository()
        else:
            self._execution_repo = NullExecutionRepository()
            self._audit_repo = NullAuditRepository()

        # 6. Build LLM client and execution engine
        try:
            self._llm_client = LLMClient(self._config)
            self._engine = ExecutionEngine(
                llm_client=self._llm_client,
                tool_registry=self._tool_registry,
                config=self._config,
            )
        except Exception:
            logger.warning("Failed to init LLM client/engine", exc_info=True)

        agent_count = len(self._workspace.agents) if self._workspace else 0
        logger.info(
            "Gateway started: %d agents, workspace=%s",
            agent_count,
            self._workspace_path,
        )

    async def _shutdown(self) -> None:
        """Clean up resources on shutdown."""
        if self._llm_client:
            await self._llm_client.close()

        if self._db_engine is not None:
            await self._db_engine.dispose()

        logger.info("Gateway shut down")

    def _register_routes(self) -> None:
        """Mount all /v1/ API routes."""
        from agent_gateway.api.routes.base import GatewayAPIRoute
        from agent_gateway.api.routes.executions import router as executions_router
        from agent_gateway.api.routes.health import router as health_router
        from agent_gateway.api.routes.introspection import router as introspection_router
        from agent_gateway.api.routes.invoke import router as invoke_router

        v1 = APIRouter(prefix="/v1", route_class=GatewayAPIRoute)
        v1.include_router(health_router)
        v1.include_router(invoke_router)
        v1.include_router(executions_router)
        v1.include_router(introspection_router)

        self.include_router(v1)

    async def _reload_workspace(self) -> None:
        """Reload workspace from disk and rebuild registry."""
        ws_path = Path(self._workspace_path)
        new_workspace = load_workspace(ws_path)

        # Rebuild tool registry with new file tools + existing code tools
        new_registry = ToolRegistry()
        new_registry.register_file_tools(new_workspace.tools)
        for code_tool in self._pending_tools:
            new_registry.register_code_tool(code_tool)

        # Atomic swap
        self._workspace = new_workspace
        self._tool_registry = new_registry

        # Update engine with new registry
        if self._engine and self._config:
            self._engine = ExecutionEngine(
                llm_client=self._llm_client,  # type: ignore[arg-type]
                tool_registry=new_registry,
                config=self._config,
            )

        logger.info("Workspace reloaded: %d agents", len(new_workspace.agents))

    async def invoke(
        self,
        agent_id: str,
        message: str,
        context: dict[str, Any] | None = None,
        options: ExecutionOptions | None = None,
    ) -> ExecutionResult:
        """Invoke an agent programmatically (bypasses HTTP).

        Args:
            agent_id: The agent to invoke.
            message: The user message.
            context: Optional context dict.
            options: Optional execution options.

        Returns:
            ExecutionResult with output, usage, and stop reason.

        Raises:
            ValueError: If agent not found or engine not available.
        """
        if self._workspace is None:
            raise ValueError("Workspace not loaded")

        agent = self._workspace.agents.get(agent_id)
        if agent is None:
            available = sorted(self._workspace.agents.keys())
            raise ValueError(
                f"Agent '{agent_id}' not found. Available: {', '.join(available)}"
            )

        if self._engine is None:
            raise ValueError("Execution engine not initialized")

        handle = ExecutionHandle(execution_id="programmatic")
        return await self._engine.execute(
            agent=agent,
            message=message,
            workspace=self._workspace,
            context=context,
            options=options,
            handle=handle,
            tool_executor=execute_tool,
        )

    def on(
        self, event: str
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register an event hook.

        Usage:
            @gw.on("execution.completed")
            async def on_complete(data):
                ...
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._event_hooks.setdefault(event, []).append(fn)
            return fn

        return decorator

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
