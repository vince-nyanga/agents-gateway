"""Gateway - FastAPI subclass for AI agent services."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

from fastapi import APIRouter, FastAPI

from agent_gateway.chat.session import ChatSession, SessionStore
from agent_gateway.config import GatewayConfig
from agent_gateway.engine.executor import ExecutionEngine
from agent_gateway.engine.llm import LLMClient
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
)
from agent_gateway.hooks import HookRegistry
from agent_gateway.persistence.null import NullAuditRepository, NullExecutionRepository
from agent_gateway.persistence.protocols import AuditRepository, ExecutionRepository
from agent_gateway.tools.runner import execute_tool
from agent_gateway.workspace.loader import WorkspaceState, load_workspace
from agent_gateway.workspace.prompt import assemble_system_prompt
from agent_gateway.workspace.registry import CodeTool, ToolRegistry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_EXECUTIONS = 50


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Immutable bundle of workspace + registry + engine for atomic reload."""

    workspace: WorkspaceState
    tool_registry: ToolRegistry
    engine: ExecutionEngine | None


class Gateway(FastAPI):
    """An opinionated FastAPI extension for building API-first AI agent services.

    Subclasses FastAPI directly. Everything you can do with a FastAPI app,
    you can do with a Gateway.
    """

    def __init__(
        self,
        workspace: str | Path = "./workspace",
        auth: bool = True,
        reload: bool = False,
        **fastapi_kwargs: Any,
    ) -> None:
        self._workspace_path = str(workspace)
        self._auth_enabled = auth
        self._reload_enabled = reload
        self._pending_tools: list[CodeTool] = []
        self._hooks = HookRegistry()

        # Initialized during lifespan startup
        self._config: GatewayConfig | None = None
        self._snapshot: WorkspaceSnapshot | None = None
        self._llm_client: LLMClient | None = None
        self._db_engine: AsyncEngine | None = None
        self._execution_repo: ExecutionRepository = NullExecutionRepository()
        self._audit_repo: AuditRepository = NullAuditRepository()
        self._execution_handles: dict[str, ExecutionHandle] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._execution_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_EXECUTIONS)
        self._reload_lock = asyncio.Lock()
        self._session_store: SessionStore | None = None
        self._session_cleanup_task: asyncio.Task[None] | None = None

        # Extract user lifespan before we override it
        user_lifespan = fastapi_kwargs.pop("lifespan", None)
        fastapi_kwargs["lifespan"] = self._make_lifespan(user_lifespan)

        super().__init__(**fastapi_kwargs)

        # Register routes eagerly (they don't depend on workspace state)
        self._register_routes()

    def _make_lifespan(self, user_lifespan: Callable[..., Any] | None) -> Any:
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

    # --- Public read-only accessors (010: programmatic parity) ---

    @property
    def workspace(self) -> WorkspaceState | None:
        """Current workspace state."""
        return self._snapshot.workspace if self._snapshot else None

    @property
    def tool_registry(self) -> ToolRegistry | None:
        """Current tool registry."""
        return self._snapshot.tool_registry if self._snapshot else None

    @property
    def engine(self) -> ExecutionEngine | None:
        """Current execution engine."""
        return self._snapshot.engine if self._snapshot else None

    @property
    def agents(self) -> dict[str, Any]:
        """Discovered agents (empty dict if workspace not loaded)."""
        ws = self.workspace
        return dict(ws.agents) if ws else {}

    @property
    def skills(self) -> dict[str, Any]:
        """Discovered skills."""
        ws = self.workspace
        return dict(ws.skills) if ws else {}

    @property
    def tools(self) -> dict[str, Any]:
        """Registered tools."""
        reg = self.tool_registry
        return dict(reg.get_all()) if reg else {}

    def health(self) -> dict[str, Any]:
        """Return gateway health info (programmatic equivalent of GET /v1/health)."""
        ws = self.workspace
        errors = ws.errors if ws else ["Workspace not loaded"]
        return {
            "status": "ok" if not errors else "degraded",
            "agent_count": len(ws.agents) if ws else 0,
            "skill_count": len(ws.skills) if ws else 0,
            "tool_count": len(self.tools),
        }

    # --- Lifecycle ---

    @asynccontextmanager
    async def managed(self) -> AsyncIterator[Gateway]:
        """Context manager for non-ASGI usage (CLI, scripts, tests).

        Usage::

            async with Gateway(workspace="./ws") as gw:
                result = await gw.invoke("agent", "hello")
        """
        await self._startup()
        try:
            yield self
        finally:
            await self._shutdown()

    async def __aenter__(self) -> Gateway:
        await self._startup()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._shutdown()

    def _setup_logging(self) -> None:
        """Configure centralized logging with structured format."""
        log_level = logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
            force=True,
        )
        # Suppress noisy libraries
        logging.getLogger("litellm").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("opentelemetry").setLevel(logging.WARNING)

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
        workspace: WorkspaceState
        try:
            workspace = load_workspace(ws_path)
            if workspace.errors:
                for err in workspace.errors:
                    logger.warning("Workspace error: %s", err)
        except Exception:
            logger.warning("Failed to load workspace", exc_info=True)
            workspace = WorkspaceState(
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
        tool_registry = ToolRegistry()
        tool_registry.register_file_tools(workspace.tools)
        for code_tool in self._pending_tools:
            tool_registry.register_code_tool(code_tool)

        # 5. Init persistence (graceful fallback)
        if self._config.persistence.enabled:
            try:
                from agent_gateway.persistence.repository import (
                    AuditRepository as AuditRepo,
                )
                from agent_gateway.persistence.repository import (
                    ExecutionRepository as ExecRepo,
                )
                from agent_gateway.persistence.session import (
                    create_db_engine,
                    create_session_factory,
                    init_db,
                )

                self._db_engine = create_db_engine(self._config.persistence)
                await init_db(self._db_engine)
                session_factory = create_session_factory(self._db_engine)
                self._execution_repo = ExecRepo(session_factory)
                self._audit_repo = AuditRepo(session_factory)
            except Exception:
                logger.warning("Failed to init persistence, using null repos", exc_info=True)

        # 6. Build LLM client and execution engine
        engine: ExecutionEngine | None = None
        try:
            self._llm_client = LLMClient(self._config)
            engine = ExecutionEngine(
                llm_client=self._llm_client,
                tool_registry=tool_registry,
                config=self._config,
                hooks=self._hooks,
            )
        except Exception:
            logger.warning("Failed to init LLM client/engine", exc_info=True)

        # 7. Atomic snapshot
        self._snapshot = WorkspaceSnapshot(
            workspace=workspace,
            tool_registry=tool_registry,
            engine=engine,
        )

        # 8. Initialize session store for multi-turn chat
        self._session_store = SessionStore()
        self._session_cleanup_task = asyncio.create_task(
            self._session_cleanup_loop(), name="session-cleanup"
        )

        # 9. Wire auth middleware if enabled
        if self._auth_enabled and self._config.auth.enabled and self._config.auth.api_keys:
            from agent_gateway.api.auth import ApiKeyAuthMiddleware

            valid_keys = {k.key: k.scopes for k in self._config.auth.api_keys}
            self.add_middleware(ApiKeyAuthMiddleware, valid_keys=valid_keys)  # type: ignore[arg-type]

        agent_count = len(workspace.agents)
        logger.info(
            "Gateway started: %d agents, workspace=%s",
            agent_count,
            self._workspace_path,
        )

        await self._hooks.fire("gateway.startup")

    async def _session_cleanup_loop(self) -> None:
        """Periodically clean up expired chat sessions."""
        try:
            while True:
                await asyncio.sleep(60)
                if self._session_store is not None:
                    self._session_store.cleanup_expired()
        except asyncio.CancelledError:
            pass

    async def _shutdown(self) -> None:
        """Clean up resources on shutdown."""
        await self._hooks.fire("gateway.shutdown")

        # Cancel session cleanup task
        if self._session_cleanup_task is not None:
            self._session_cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._session_cleanup_task

        # Cancel and await all background tasks
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        if self._llm_client:
            await self._llm_client.close()

        if self._db_engine is not None:
            await self._db_engine.dispose()

        logger.info("Gateway shut down")

    def _register_routes(self) -> None:
        """Mount all /v1/ API routes."""
        from agent_gateway.api.routes.base import GatewayAPIRoute
        from agent_gateway.api.routes.chat import router as chat_router
        from agent_gateway.api.routes.executions import router as executions_router
        from agent_gateway.api.routes.health import router as health_router
        from agent_gateway.api.routes.introspection import router as introspection_router
        from agent_gateway.api.routes.invoke import router as invoke_router

        v1 = APIRouter(prefix="/v1", route_class=GatewayAPIRoute)
        v1.include_router(health_router)
        v1.include_router(invoke_router)
        v1.include_router(chat_router)
        v1.include_router(executions_router)
        v1.include_router(introspection_router)

        self.include_router(v1)

    async def reload(self) -> None:
        """Reload workspace from disk and rebuild registry (atomic snapshot swap)."""
        async with self._reload_lock:
            ws_path = Path(self._workspace_path)
            new_workspace = load_workspace(ws_path)

            new_registry = ToolRegistry()
            new_registry.register_file_tools(new_workspace.tools)
            for code_tool in self._pending_tools:
                new_registry.register_code_tool(code_tool)

            new_engine: ExecutionEngine | None = None
            if self._llm_client and self._config:
                new_engine = ExecutionEngine(
                    llm_client=self._llm_client,
                    tool_registry=new_registry,
                    config=self._config,
                    hooks=self._hooks,
                )

            # Single atomic reference swap
            self._snapshot = WorkspaceSnapshot(
                workspace=new_workspace,
                tool_registry=new_registry,
                engine=new_engine,
            )

            logger.info("Workspace reloaded: %d agents", len(new_workspace.agents))

    async def _reload_workspace(self) -> None:
        """Alias for backward compatibility."""
        await self.reload()

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
        snapshot = self._snapshot
        if snapshot is None or snapshot.workspace is None:
            raise ValueError("Workspace not loaded")

        agent = snapshot.workspace.agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' not found")

        if snapshot.engine is None:
            raise ValueError("Execution engine not initialized")

        execution_id = str(uuid.uuid4())
        handle = ExecutionHandle(execution_id=execution_id)
        self._execution_handles[execution_id] = handle

        try:
            return await snapshot.engine.execute(
                agent=agent,
                message=message,
                workspace=snapshot.workspace,
                context=context,
                options=options,
                handle=handle,
                tool_executor=execute_tool,
            )
        finally:
            self._execution_handles.pop(execution_id, None)

    async def chat(
        self,
        agent_id: str,
        message: str,
        session_id: str | None = None,
        context: dict[str, Any] | None = None,
        options: ExecutionOptions | None = None,
    ) -> tuple[str, ExecutionResult]:
        """Send a chat message programmatically (bypasses HTTP).

        Args:
            agent_id: The agent to chat with.
            message: The user message.
            session_id: Optional existing session ID. Creates new session if None.
            context: Optional context dict.
            options: Optional execution options.

        Returns:
            Tuple of (session_id, ExecutionResult).

        Raises:
            ValueError: If agent not found, engine not available, or session mismatch.
        """
        snapshot = self._snapshot
        if snapshot is None or snapshot.workspace is None:
            raise ValueError("Workspace not loaded")

        agent = snapshot.workspace.agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' not found")

        if snapshot.engine is None:
            raise ValueError("Execution engine not initialized")

        if self._session_store is None:
            raise ValueError("Session store not initialized")

        # Get or create session
        if session_id:
            session = self._session_store.get_session(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            if session.agent_id != agent_id:
                raise ValueError(
                    f"Session '{session_id}' belongs to agent "
                    f"'{session.agent_id}', not '{agent_id}'"
                )
        else:
            session = self._session_store.create_session(agent_id, metadata=context)

        if context:
            session.merge_metadata(context)

        async with session.lock:
            session.append_user_message(message)
            session.truncate_history(self._session_store._max_history)

            system_prompt = assemble_system_prompt(agent, snapshot.workspace)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                *session.messages,
            ]

            execution_id = str(uuid.uuid4())
            handle = ExecutionHandle(execution_id=execution_id)
            self._execution_handles[execution_id] = handle

            start = time.monotonic()
            try:
                result = await snapshot.engine.execute(
                    agent=agent,
                    message=message,
                    workspace=snapshot.workspace,
                    context=session.metadata,
                    options=options,
                    handle=handle,
                    tool_executor=execute_tool,
                    message_history=messages,
                )
            finally:
                self._execution_handles.pop(execution_id, None)

            result.duration_ms = int((time.monotonic() - start) * 1000)

            if result.raw_text:
                session.append_assistant_message(content=result.raw_text)

            return session.session_id, result

    # --- Programmatic session management ---

    def get_session(self, session_id: str) -> ChatSession | None:
        """Get a session by ID."""
        if self._session_store is None:
            return None
        return self._session_store.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        if self._session_store is None:
            return False
        return self._session_store.delete_session(session_id)

    def list_sessions(
        self,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[ChatSession]:
        """List active sessions."""
        if self._session_store is None:
            return []
        return self._session_store.list_sessions(agent_id=agent_id, limit=limit)

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running execution. Returns True if cancelled."""
        handle = self._execution_handles.get(execution_id)
        if handle is None:
            return False
        handle.cancel()
        return True

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
        1. Explicit ``parameters`` dict -- used as-is, no inference.
        2. Single Pydantic model parameter -- schema from model_json_schema().
        3. ``Annotated[type, "description"]`` -- type + description extracted.
        4. Bare type hints -- type inferred, parameter name used as description.
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

    def on(self, event: str) -> Callable[..., Any]:
        """Register a lifecycle hook callback.

        Usage::

            @gw.on("agent.invoke.before")
            async def on_invoke(agent_id, message, execution_id, **kw):
                print(f"Invoking {agent_id}")
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._hooks.register(event, fn)
            return fn

        return decorator

    def run(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        **kwargs: object,
    ) -> None:
        """Start the gateway server using uvicorn."""
        import uvicorn

        self._setup_logging()
        uvicorn.run(self, host=host, port=port, **kwargs)  # type: ignore[arg-type]
