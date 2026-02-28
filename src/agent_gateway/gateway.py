"""Gateway - FastAPI subclass for AI agent services."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

from fastapi import APIRouter, FastAPI

if TYPE_CHECKING:
    from datetime import datetime

    from agent_gateway.memory.manager import MemoryManager
    from agent_gateway.memory.protocols import MemoryBackend
    from agent_gateway.scheduler.engine import SchedulerEngine

from agent_gateway.auth.protocols import AuthProvider
from agent_gateway.chat.session import ChatSession, SessionStore
from agent_gateway.config import (
    ContextRetrievalConfig,
    CorsConfig,
    GatewayConfig,
    NotificationsConfig,
    PersistenceConfig,
    RateLimitConfig,
    SecurityConfig,
)
from agent_gateway.context.protocol import ContextRetriever
from agent_gateway.context.registry import RetrieverRegistry
from agent_gateway.engine.executor import ExecutionEngine
from agent_gateway.engine.llm import LLMClient
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
)
from agent_gateway.hooks import HookRegistry
from agent_gateway.notifications import NotificationEngine
from agent_gateway.notifications.models import (
    build_notification_event,
    build_notification_job,
    sanitize_target,
)
from agent_gateway.notifications.protocols import NotificationBackend
from agent_gateway.persistence.backend import PersistenceBackend
from agent_gateway.persistence.domain import NotificationDeliveryRecord
from agent_gateway.persistence.null import (
    NullAuditRepository,
    NullConversationRepository,
    NullExecutionRepository,
    NullMcpServerRepository,
    NullNotificationRepository,
    NullScheduleRepository,
    NullUserAgentConfigRepository,
    NullUserRepository,
    NullUserScheduleRepository,
)
from agent_gateway.persistence.protocols import (
    AuditRepository,
    ConversationRepository,
    ExecutionRepository,
    McpServerRepository,
    NotificationRepository,
    ScheduleRepository,
    UserAgentConfigRepository,
    UserRepository,
    UserScheduleRepository,
)
from agent_gateway.queue.null import NullQueue
from agent_gateway.queue.protocol import ExecutionQueue
from agent_gateway.tools.runner import execute_tool
from agent_gateway.workspace.loader import WorkspaceState, load_workspace
from agent_gateway.workspace.prompt import assemble_system_prompt
from agent_gateway.workspace.registry import CodeTool, ToolRegistry

logger = logging.getLogger(__name__)

_AUTH_NOT_SET = object()  # sentinel: distinguishes "not configured" from "explicitly disabled"
_MAX_CONCURRENT_EXECUTIONS = 50

_GATEWAY_OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "Health", "description": "Gateway health and readiness checks."},
    {"name": "Agents", "description": "Agent invocation and introspection."},
    {"name": "Chat", "description": "Multi-turn conversational sessions."},
    {"name": "Sessions", "description": "Session lifecycle management."},
    {"name": "Conversations", "description": "Persistent conversation history."},
    {"name": "Executions", "description": "Execution history, polling, and cancellation."},
    {"name": "Schedules", "description": "Cron schedule management."},
    {"name": "Tools", "description": "Tool registry introspection."},
    {"name": "Skills", "description": "Skill registry introspection."},
    {"name": "User Config", "description": "Per-user agent configuration (personal agents)."},
    {"name": "Notifications", "description": "Notification delivery log and status."},
    {"name": "Admin", "description": "Administrative operations."},
]


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Immutable bundle of workspace + registry + engine for atomic reload."""

    workspace: WorkspaceState
    tool_registry: ToolRegistry
    engine: ExecutionEngine | None
    retriever_registry: RetrieverRegistry | None = None
    context_retrieval_config: ContextRetrievalConfig | None = None


class Gateway(FastAPI):
    """A FastAPI extension for building API-first AI agent services.

    Subclasses FastAPI directly. Everything you can do with a FastAPI app,
    you can do with a Gateway.
    """

    def __init__(
        self,
        workspace: str | Path = "./workspace",
        auth: bool | Callable[..., Any] | AuthProvider = True,
        reload: bool = False,
        **fastapi_kwargs: Any,
    ) -> None:
        self._workspace_path = str(workspace)
        self._auth_setting = auth
        self._reload_enabled = reload
        self._pending_tools: list[CodeTool] = []
        self._pending_input_schemas: dict[str, dict[str, Any] | type] = {}
        self._pending_retrievers: dict[str, ContextRetriever] = {}
        self._retriever_registry: RetrieverRegistry | None = None
        self._hooks = HookRegistry()

        # Initialized during lifespan startup
        self._config: GatewayConfig | None = None
        self._snapshot: WorkspaceSnapshot | None = None
        self._llm_client: LLMClient | None = None
        self._persistence_backend: PersistenceBackend | None = None
        self._auth_provider: AuthProvider | None | object = _AUTH_NOT_SET  # fluent API
        self._started = False
        self._execution_repo: ExecutionRepository = NullExecutionRepository()
        self._audit_repo: AuditRepository = NullAuditRepository()
        self._execution_handles: dict[str, ExecutionHandle] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._execution_semaphore: asyncio.Semaphore | None = None  # created in _startup
        self._reload_lock = asyncio.Lock()
        self._session_store: SessionStore | None = None
        self._session_cleanup_task: asyncio.Task[None] | None = None
        self._queue_backend: ExecutionQueue | NullQueue | None = None  # fluent API
        self._queue: ExecutionQueue | NullQueue = NullQueue()
        self._worker_pool: Any = None  # WorkerPool, set during startup
        self._notification_engine = NotificationEngine()
        self._notification_backends: list[NotificationBackend] = []  # pre-startup buffer
        self._notification_queue: Any | None = None  # notification queue backend
        self._notification_queue_backend: Any | None = None  # fluent API override
        self._notification_worker: Any | None = None  # NotificationWorker
        self._scheduler: SchedulerEngine | None = None
        self._schedule_repo: ScheduleRepository = NullScheduleRepository()
        self._user_repo: UserRepository = NullUserRepository()
        self._conversation_repo: ConversationRepository = NullConversationRepository()
        self._user_agent_config_repo: UserAgentConfigRepository = NullUserAgentConfigRepository()
        self._user_schedule_repo: UserScheduleRepository = NullUserScheduleRepository()
        self._notification_repo: NotificationRepository = NullNotificationRepository()
        self._pending_mcp_servers: list[dict[str, Any]] = []  # raw dicts, encrypted at startup
        self._mcp_repo: McpServerRepository = NullMcpServerRepository()
        self._mcp_manager: Any | None = None  # McpConnectionManager, set during startup
        self._pending_memory_backend: MemoryBackend | None = None  # fluent API
        self._memory_manager: MemoryManager | None = None
        self._pending_cors_config: CorsConfig | None = None  # fluent API
        self._pending_rate_limit_config: RateLimitConfig | None = None  # fluent API
        self._pending_security_config: SecurityConfig | None = None  # fluent API
        self._pending_dashboard_overrides: dict[str, Any] = {}  # fluent API
        self._oauth2_issuer: str | None = None  # for OpenAPI security scheme
        self._extraction_cooldowns: dict[str, float] = {}
        _EXTRACTION_DEBOUNCE_SECONDS = 30.0
        self._extraction_debounce = _EXTRACTION_DEBOUNCE_SECONDS
        self._rehydration_tasks: dict[str, asyncio.Task[ChatSession | None]] = {}
        self._mount_prefix: str = ""  # set by mount_to(); empty for standalone

        # Merge default OpenAPI tags with any caller-supplied tags (de-duplicate by name)
        caller_tags = fastapi_kwargs.pop("openapi_tags", None) or []
        gateway_names = {t["name"] for t in _GATEWAY_OPENAPI_TAGS}
        extra_tags = [t for t in caller_tags if t.get("name") not in gateway_names]
        fastapi_kwargs["openapi_tags"] = [*_GATEWAY_OPENAPI_TAGS, *extra_tags]

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

    @property
    def memory_manager(self) -> MemoryManager | None:
        """The memory manager, if memory is enabled."""
        return self._memory_manager

    def is_agent_enabled(self, agent_id: str) -> bool:
        """Check if an agent is enabled (from AGENT.md frontmatter)."""
        agent = self.agents.get(agent_id)
        if agent is None:
            return False
        return bool(agent.enabled)

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

    def mount_to(
        self,
        parent: FastAPI,
        path: str = "/gateway",
    ) -> FastAPI:
        """Mount this gateway as a sub-application of an existing FastAPI app.

        Wires the gateway's startup/shutdown into the parent app's lifespan
        and mounts the gateway at the given path prefix. All features work
        including the dashboard, auth, OAuth2, and static assets.

        Usage::

            from fastapi import FastAPI
            from agent_gateway import Gateway

            app = FastAPI()
            gw = Gateway(workspace="./workspace")
            gw.use_dashboard(
                auth_password="secret",
                admin_username="admin",
                admin_password="admin",
            )
            gw.mount_to(app, path="/gateway")

            # Dashboard at /gateway/dashboard/
            # API at /gateway/v1/...
        """
        from agent_gateway.exceptions import ConfigError

        if self._started:
            raise ConfigError("Cannot mount_to() after gateway has already started")

        # Normalize: strip trailing slash, ensure leading slash
        stripped = path.strip("/")
        if not stripped:
            raise ConfigError("mount_to() requires a non-empty path prefix, e.g. '/gateway'")
        path = f"/{stripped}"
        self._mount_prefix = path

        # Wrap the parent app's lifespan to include gateway startup/shutdown
        original_lifespan = parent.router.lifespan_context

        @asynccontextmanager
        async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with self.managed():
                if original_lifespan is not None:
                    async with original_lifespan(app):
                        yield
                else:
                    yield

        parent.router.lifespan_context = combined_lifespan

        # Mount the gateway as a sub-application
        parent.mount(path, self)

        return parent

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
        if self._started:
            logger.warning("Gateway already started, skipping duplicate _startup()")
            return

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
        retriever_names = frozenset(self._pending_retrievers.keys())
        try:
            workspace = load_workspace(ws_path, retriever_names=retriever_names)
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
                root_behavior_prompt="",
                warnings=[],
                errors=["Workspace failed to load"],
            )

        # 4. Build tool registry
        tool_registry = ToolRegistry()
        tool_registry.register_file_tools(workspace.tools)
        for code_tool in self._pending_tools:
            tool_registry.register_code_tool(code_tool)

        # 5. Init persistence
        backend = self._persistence_backend
        if backend is None and self._config.persistence.enabled:
            backend = self._backend_from_config(self._config.persistence)

        if backend is not None:
            try:
                await backend.initialize()
                self._persistence_backend = backend
                self._execution_repo = backend.execution_repo
                self._audit_repo = backend.audit_repo
                self._schedule_repo = backend.schedule_repo
                self._user_repo = backend.user_repo
                self._conversation_repo = backend.conversation_repo
                self._user_agent_config_repo = backend.user_agent_config_repo
                self._user_schedule_repo = backend.user_schedule_repo
                self._notification_repo = backend.notification_repo
                self._mcp_repo = backend.mcp_server_repo
            except ImportError:
                raise  # Don't swallow missing driver errors
            except Exception:
                logger.warning("Failed to init persistence, using null repos", exc_info=True)

        # 6. Init execution queue
        queue_cfg = self._config.queue
        workers = queue_cfg.workers if queue_cfg else _MAX_CONCURRENT_EXECUTIONS
        self._execution_semaphore = asyncio.Semaphore(workers)

        queue = self._queue_backend
        if queue is None:
            queue = self._queue_from_config(queue_cfg)
        if queue is not None:
            try:
                await queue.initialize()
                self._queue = queue
            except ImportError:
                raise  # Don't swallow missing driver errors
            except Exception:
                logger.warning("Failed to init queue backend, using NullQueue", exc_info=True)
                self._queue = NullQueue()

        # 6.5: Init notifications
        for nb in self._notification_backends:
            self._notification_engine.register(nb)
        if not self._notification_engine.has_backends:
            self._init_notifications_from_config(self._config.notifications)
        try:
            await self._notification_engine.initialize()
        except ImportError:
            raise
        except Exception:
            logger.warning("Failed to initialize notification backends", exc_info=True)

        # 6.6: Init notification queue (if configured)
        notif_queue = self._notification_queue_backend
        if notif_queue is not None:
            try:
                await notif_queue.initialize()
                self._notification_queue = notif_queue
            except ImportError:
                raise
            except Exception:
                logger.warning(
                    "Failed to init notification queue, using fire-and-forget fallback",
                    exc_info=True,
                )
                self._notification_queue = None

        # 6.7: Build retriever registry
        retriever_registry = RetrieverRegistry()
        for name, retriever in self._pending_retrievers.items():
            retriever_registry.register(name, retriever)
        try:
            await retriever_registry.initialize_all()
        except Exception:
            logger.warning("Failed to initialize retrievers", exc_info=True)
        self._retriever_registry = retriever_registry

        # 6.8: MCP server connections
        try:
            from agent_gateway.mcp.manager import (
                McpConnectionManager,
                compute_server_to_agents,
            )
            from agent_gateway.persistence.domain import McpServerConfig as _McpCfg
            from agent_gateway.secrets import encrypt_value as _encrypt

            # Load from DB + pending list
            db_mcp_configs = await self._mcp_repo.list_enabled()
            pending_mcp_configs: list[_McpCfg] = []
            pending_token_providers: dict[str, Any] = {}
            for raw in self._pending_mcp_servers:
                if raw.get("token_provider") is not None:
                    pending_token_providers[raw["name"]] = raw["token_provider"]
                pending_mcp_configs.append(
                    _McpCfg(
                        id=str(uuid.uuid4()),
                        name=raw["name"],
                        transport=raw["transport"],
                        command=raw.get("command"),
                        args=raw.get("args"),
                        encrypted_env=(
                            _encrypt(json.dumps(raw["env"])) if raw.get("env") else None
                        ),
                        url=raw.get("url"),
                        headers=raw.get("headers"),
                        encrypted_credentials=(
                            _encrypt(json.dumps(raw["credentials"]))
                            if raw.get("credentials")
                            else None
                        ),
                        enabled=raw.get("enabled", True),
                    )
                )

            # Merge: pending takes precedence over DB if names collide
            configs_by_name: dict[str, _McpCfg] = {}
            for c in db_mcp_configs:
                configs_by_name[c.name] = c
            for c in pending_mcp_configs:
                configs_by_name[c.name] = c  # overrides DB config with same name

            all_mcp_configs = list(configs_by_name.values())

            # Validate agent references
            known_server_names = {c.name for c in all_mcp_configs}
            for agent in workspace.agents.values():
                for server_name in agent.mcp_servers:
                    if server_name not in known_server_names:
                        logger.warning(
                            "Agent '%s' references MCP server '%s' which does not exist. "
                            "Tools from this server will not be available.",
                            agent.id,
                            server_name,
                        )

            # Connect
            if all_mcp_configs:
                self._mcp_manager = McpConnectionManager(
                    connection_timeout_ms=self._config.mcp.connection_timeout_ms,
                    tool_call_timeout_ms=self._config.mcp.tool_call_timeout_ms,
                )
                await self._mcp_manager.connect_all(
                    all_mcp_configs, token_providers=pending_token_providers
                )

                # Compute allowed_agents per server
                server_to_agents = compute_server_to_agents(workspace)

                # Register MCP tools in ToolRegistry with allowed_agents
                all_mcp_tools = self._mcp_manager.get_all_tools()
                for server_name, tools in all_mcp_tools.items():
                    allowed = server_to_agents.get(server_name)
                    tool_registry.register_mcp_tools(tools, allowed_agents=allowed)

                logger.info(
                    "MCP setup complete: %d servers connected, %d total tools registered",
                    len(self._mcp_manager._connections),
                    sum(len(t) for t in all_mcp_tools.values()),
                )
        except Exception:
            logger.warning("Failed to init MCP servers", exc_info=True)

        # 7. Build LLM client and execution engine
        engine: ExecutionEngine | None = None
        try:
            self._llm_client = LLMClient(self._config)
            engine = ExecutionEngine(
                llm_client=self._llm_client,
                tool_registry=tool_registry,
                config=self._config,
                hooks=self._hooks,
                retriever_registry=retriever_registry,
                execution_repo=self._execution_repo,
                mcp_manager=self._mcp_manager,
            )
        except Exception:
            logger.warning("Failed to init LLM client/engine", exc_info=True)

        # 7.2: Init memory
        memory_cfg = self._config.memory
        memory_backend = self._pending_memory_backend
        has_memory_agents = any(
            a.memory_config and a.memory_config.enabled for a in workspace.agents.values()
        )
        if (memory_cfg.enabled or memory_backend is not None) and has_memory_agents:
            if memory_backend is None:
                # Auto-select: SQL backend when persistence is SQL (per-user support),
                # otherwise file-based (single MEMORY.md per agent).
                if self._persistence_backend is not None and hasattr(
                    self._persistence_backend, "_session_factory"
                ):
                    from agent_gateway.memory.backends.sql import SqlMemoryBackend

                    memory_backend = SqlMemoryBackend(self._persistence_backend._session_factory)
                    logger.info("Using SQL memory backend (per-user scoping enabled)")
                else:
                    from agent_gateway.memory.backends.file import FileMemoryBackend

                    memory_backend = FileMemoryBackend(
                        workspace_root=ws_path,
                        max_lines=memory_cfg.max_memory_md_lines,
                    )
            try:
                await memory_backend.initialize()

                from agent_gateway.memory.manager import MemoryManager

                if self._llm_client is None:
                    logger.warning(
                        "Memory requires an LLM client — skipping memory initialization"
                    )
                    return
                self._memory_manager = MemoryManager(
                    backend=memory_backend,
                    llm_client=self._llm_client,
                    config=memory_cfg,
                )

                # Register memory tools for agents with memory enabled
                memory_agents = [
                    aid
                    for aid, a in workspace.agents.items()
                    if a.memory_config and a.memory_config.enabled
                ]
                if memory_agents:
                    from agent_gateway.memory.tools import make_memory_tools

                    mem_tools = make_memory_tools(self._memory_manager)
                    for tool_def in mem_tools:
                        code_tool = CodeTool(
                            name=tool_def["name"],
                            description=tool_def["description"],
                            fn=tool_def["func"],
                            parameters_schema=tool_def["parameters"],
                            allowed_agents=memory_agents,
                        )
                        tool_registry.register_code_tool(code_tool)

                logger.info(
                    "Memory initialized for %d agent(s): %s",
                    len(memory_agents),
                    ", ".join(memory_agents),
                )
            except Exception:
                logger.warning("Failed to init memory backend", exc_info=True)
                self._memory_manager = None

        # 7.3: Register delegation tool when workspace has 2+ agents
        if len(workspace.agents) >= 2:
            delegation_tool = self._build_delegation_tool(workspace)
            tool_registry.register_code_tool(delegation_tool)
            logger.info(
                "Delegation tool registered for all agents (%d agents in workspace)",
                len(workspace.agents),
            )

        # 7.5. Apply code-registered input schemas (overrides frontmatter)
        self._apply_pending_input_schemas(workspace)

        # 8. Atomic snapshot
        self._snapshot = WorkspaceSnapshot(
            workspace=workspace,
            tool_registry=tool_registry,
            engine=engine,
            retriever_registry=retriever_registry,
            context_retrieval_config=self._config.context_retrieval if self._config else None,
        )

        # 9. Initialize session store for multi-turn chat
        self._session_store = SessionStore()
        self._session_cleanup_task = asyncio.create_task(
            self._session_cleanup_loop(), name="session-cleanup"
        )

        # 9.5: Init scheduler (cron-based agent invocations)
        if self._config.scheduler.enabled and workspace.schedules:
            try:
                from agent_gateway.scheduler.engine import SchedulerEngine

                def _track_task(t: asyncio.Task[None]) -> None:
                    self._background_tasks.add(t)
                    t.add_done_callback(self._background_tasks.discard)

                # Build distributed lock if enabled
                from agent_gateway.scheduler.lock import DistributedLock as _DL

                distributed_lock: _DL | None = None
                lock_config = self._config.scheduler.distributed_lock
                if lock_config.enabled:
                    from agent_gateway.scheduler.lock import (
                        PostgresDistributedLock,
                        RedisDistributedLock,
                    )

                    lock_backend = lock_config.backend
                    if lock_backend == "auto":
                        from agent_gateway.queue.backends.redis import (
                            RedisQueue as _RQ,
                        )

                        if isinstance(self._queue, _RQ):
                            lock_backend = "redis"
                        elif hasattr(self._persistence_backend, "_engine"):
                            lock_backend = "postgres"
                        else:
                            logger.warning(
                                "distributed_lock enabled but no Redis queue or "
                                "Postgres persistence configured; "
                                "falling back to no-op lock"
                            )

                    if lock_backend == "redis":
                        redis_url = lock_config.redis_url or self._config.queue.redis_url
                        distributed_lock = RedisDistributedLock(
                            url=redis_url,
                            key_prefix=lock_config.key_prefix,
                        )
                    elif lock_backend == "postgres":
                        if self._persistence_backend is not None and hasattr(
                            self._persistence_backend, "_engine"
                        ):
                            distributed_lock = PostgresDistributedLock(
                                engine=self._persistence_backend._engine
                            )
                        else:
                            logger.warning(
                                "distributed_lock backend=postgres but no "
                                "Postgres persistence configured"
                            )

                self._scheduler = SchedulerEngine(
                    config=self._config.scheduler,
                    schedule_repo=self._schedule_repo,
                    execution_repo=self._execution_repo,
                    queue=self._queue,
                    invoke_fn=self.invoke,
                    track_task=_track_task,
                    timezone=self._config.timezone,
                    distributed_lock=distributed_lock,
                )
                await self._scheduler.start(
                    agents=workspace.agents,
                )
            except ImportError:
                raise
            except Exception:
                logger.warning("Failed to init scheduler", exc_info=True)
                self._scheduler = None

        # 10. Start worker pool for queue-based async execution
        if not isinstance(self._queue, NullQueue):
            from agent_gateway.queue.worker import WorkerPool

            self._worker_pool = WorkerPool(
                queue=self._queue,
                gateway=self,
                config=self._config.queue,
            )
            await self._worker_pool.start()

        # 10.5: Start notification worker if notification queue is configured
        if self._notification_queue is not None and self._notification_engine.has_backends:
            from agent_gateway.notifications.worker import NotificationWorker

            self._notification_worker = NotificationWorker(
                queue=self._notification_queue,
                engine=self._notification_engine,
                notification_repo=self._notification_repo,
            )
            await self._notification_worker.start()

        # 10b. Wire CORS middleware if enabled
        if self._pending_cors_config is not None:
            self._config.cors = self._pending_cors_config
        if self._config.cors.enabled:
            from starlette.middleware.cors import CORSMiddleware

            cors = self._config.cors
            cors_kwargs: dict[str, Any] = {
                "allow_origins": cors.allow_origins,
                "allow_methods": cors.allow_methods,
                "allow_headers": cors.allow_headers,
                "allow_credentials": cors.allow_credentials,
                "max_age": cors.max_age,
            }
            if self.middleware_stack is not None:
                self.middleware_stack = CORSMiddleware(app=self.middleware_stack, **cors_kwargs)
            else:
                self.add_middleware(CORSMiddleware, **cors_kwargs)

        # 10c. Wire rate limiting middleware if enabled
        if self._pending_rate_limit_config is not None:
            self._config.rate_limit = self._pending_rate_limit_config
        if self._config.rate_limit.enabled:
            if self._config.server.workers > 1 and not self._config.rate_limit.storage_uri:
                logger.warning(
                    "Rate limiting is enabled with multiple workers but no storage_uri "
                    "configured. Limits are per-process and will not be enforced across "
                    "workers. Set rate_limit.storage_uri to a Redis URL for shared rate "
                    "limiting."
                )
            from agent_gateway.ratelimit import setup_rate_limiting

            result = setup_rate_limiting(self, self._config.rate_limit)
            if result is not None:
                _, middleware_class = result
                if self.middleware_stack is not None:
                    self.middleware_stack = middleware_class(self.middleware_stack)
                else:
                    self.add_middleware(middleware_class)  # type: ignore[arg-type]

        # 11. Wire auth middleware if enabled
        auth_provider = self._resolve_auth_provider()
        if auth_provider is not None:
            from agent_gateway.auth.middleware import AuthMiddleware

            public = frozenset(self._config.auth.public_paths)
            if self.middleware_stack is not None:
                # Lifespan path (uvicorn): middleware_stack already built,
                # add_middleware() would raise, so wrap directly.
                self.middleware_stack = AuthMiddleware(  # type: ignore[assignment]
                    app=self.middleware_stack,  # type: ignore[arg-type]
                    provider=auth_provider,
                    public_paths=public,
                )
            else:
                # __aenter__ path (tests/scripts): middleware_stack not yet
                # built, so add_middleware() is safe.
                self.add_middleware(
                    AuthMiddleware,
                    provider=auth_provider,
                    public_paths=public,
                )

        # 11b. Add OpenAPI security scheme (enables Swagger UI Authorize button)
        if auth_provider is not None:
            await self._inject_openapi_security_scheme()

        # 11c. Wire security headers middleware if enabled (outermost layer so
        # headers are applied even when CORS or auth short-circuit responses).
        if self._pending_security_config is not None:
            self._config.security = self._pending_security_config
        if self._config.security.enabled:
            from agent_gateway.api.middleware.security import SecurityHeadersMiddleware

            if self.middleware_stack is not None:
                self.middleware_stack = SecurityHeadersMiddleware(
                    app=self.middleware_stack,
                    config=self._config.security,
                )
            else:
                self.add_middleware(SecurityHeadersMiddleware, config=self._config.security)

        # 12. Mount dashboard if enabled
        self._maybe_init_dashboard()

        self._started = True

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
        if not self._started:
            logger.debug("Gateway already shut down, skipping duplicate _shutdown()")
            return
        # Disconnect MCP servers first
        if self._mcp_manager is not None:
            try:
                await self._mcp_manager.disconnect_all()
            except Exception:
                logger.warning("Failed to disconnect MCP servers", exc_info=True)
            self._mcp_manager = None

        await self._hooks.fire("gateway.shutdown")

        # Stop scheduler (prevents new cron fires; in-flight jobs finish via worker pool)
        if self._scheduler is not None:
            await self._scheduler.stop()
            self._scheduler = None

        # Drain worker pool (waits for in-flight jobs up to drain_timeout_s)
        if self._worker_pool is not None:
            await self._worker_pool.drain()
            self._worker_pool = None

        # Drain notification worker
        if self._notification_worker is not None:
            await self._notification_worker.drain()
            self._notification_worker = None

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

        # Dispose notification engine
        if self._notification_engine.has_backends:
            await self._notification_engine.dispose()

        # Dispose memory backend
        if self._memory_manager is not None:
            try:
                await self._memory_manager.dispose()
            except Exception:
                logger.warning("Failed to dispose memory backend", exc_info=True)
            self._memory_manager = None

        # Close retrievers
        if self._retriever_registry is not None:
            await self._retriever_registry.close_all()

        if self._llm_client:
            await self._llm_client.close()

        if self._auth_provider is not _AUTH_NOT_SET and self._auth_provider is not None:
            assert isinstance(self._auth_provider, AuthProvider)
            await self._auth_provider.close()

        # Dispose queue backend
        if not isinstance(self._queue, NullQueue):
            await self._queue.dispose()
            self._queue = NullQueue()

        # Dispose notification queue
        if self._notification_queue is not None:
            await self._notification_queue.dispose()
            self._notification_queue = None

        if self._persistence_backend is not None:
            await self._persistence_backend.dispose()

        self._started = False
        logger.info("Gateway shut down")

    # --- Persistence configuration (fluent API) ---

    def use_sqlite(
        self,
        path: str = "agent_gateway.db",
        table_prefix: str = "",
    ) -> Gateway:
        """Configure SQLite persistence.

        Requires: pip install agent-gateway[sqlite]

        Args:
            path: Path to the SQLite database file, or ":memory:" for in-memory.
            table_prefix: Optional prefix for table names (e.g. "ag_").
        """
        if self._started:
            raise RuntimeError("Cannot configure persistence after gateway has started")
        from agent_gateway.persistence.backends.sqlite import SqliteBackend

        self._persistence_backend = SqliteBackend(path=path, table_prefix=table_prefix)
        return self

    def use_postgres(
        self,
        url: str,
        schema: str | None = None,
        table_prefix: str = "",
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> Gateway:
        """Configure PostgreSQL persistence.

        Requires: pip install agent-gateway[postgres]

        Args:
            url: PostgreSQL DSN (e.g. "postgresql+asyncpg://user:pass@host/db").
            schema: PostgreSQL schema name (must pre-exist).
            table_prefix: Optional prefix for table names (e.g. "ag_").
            pool_size: Connection pool size.
            max_overflow: Max connections beyond pool_size.
        """
        if self._started:
            raise RuntimeError("Cannot configure persistence after gateway has started")
        from agent_gateway.persistence.backends.postgres import PostgresBackend

        self._persistence_backend = PostgresBackend(
            url=url,
            schema=schema,
            table_prefix=table_prefix,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        return self

    def use_persistence(self, backend: PersistenceBackend | None) -> Gateway:
        """Configure a custom persistence backend, or None to disable.

        Args:
            backend: A PersistenceBackend implementation, or None for NullPersistence.
        """
        if self._started:
            raise RuntimeError("Cannot configure persistence after gateway has started")
        self._persistence_backend = backend
        return self

    # --- Queue configuration (fluent API) ---

    def use_memory_queue(self) -> Gateway:
        """Use in-process asyncio.Queue for async execution.

        Development and testing only. Jobs are lost on server restart.
        Single-process only — ``--worker-only`` mode is not supported.
        """
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        from agent_gateway.queue.backends.memory import MemoryQueue

        self._queue_backend = MemoryQueue()

        from agent_gateway.notifications.queue_backends import MemoryNotificationQueue

        self._notification_queue_backend = MemoryNotificationQueue()
        return self

    def use_redis_queue(
        self,
        url: str = "redis://localhost:6379/0",
        stream_key: str = "ag:executions",
        consumer_group: str = "ag-workers",
    ) -> Gateway:
        """Configure Redis Streams queue backend for async execution.

        Requires: pip install agent-gateway[redis]

        Args:
            url: Redis connection URL.
            stream_key: Redis stream name for jobs.
            consumer_group: Consumer group name for coordinating workers.
        """
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        from agent_gateway.queue.backends.redis import RedisQueue

        self._queue_backend = RedisQueue(
            url=url, stream_key=stream_key, consumer_group=consumer_group
        )

        from agent_gateway.notifications.queue_backends import RedisNotificationQueue

        self._notification_queue_backend = RedisNotificationQueue(url=url)
        return self

    def use_rabbitmq_queue(
        self,
        url: str = "amqp://guest:guest@localhost:5672/",
        queue_name: str = "ag.executions",
    ) -> Gateway:
        """Configure RabbitMQ queue backend for async execution.

        Requires: pip install agent-gateway[rabbitmq]

        Args:
            url: AMQP connection URL.
            queue_name: Durable queue name for jobs.
        """
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        from agent_gateway.queue.backends.rabbitmq import RabbitMQQueue

        self._queue_backend = RabbitMQQueue(url=url, queue_name=queue_name)

        from agent_gateway.notifications.queue_backends import RabbitMQNotificationQueue

        self._notification_queue_backend = RabbitMQNotificationQueue(url=url)
        return self

    def use_queue(self, backend: ExecutionQueue | None) -> Gateway:
        """Configure a custom queue backend, or None to disable.

        Args:
            backend: An ExecutionQueue implementation, or None for NullQueue.
        """
        if self._started:
            raise RuntimeError("Cannot configure queue after gateway has started")
        self._queue_backend = backend
        return self

    def _queue_from_config(self, config: Any) -> Any:
        """Create a queue backend from gateway.yaml config."""
        if config is None:
            return None
        backend = config.backend
        if backend == "memory":
            from agent_gateway.notifications.queue_backends import MemoryNotificationQueue
            from agent_gateway.queue.backends.memory import MemoryQueue

            self._notification_queue_backend = MemoryNotificationQueue()
            return MemoryQueue()
        elif backend == "redis":
            from agent_gateway.notifications.queue_backends import RedisNotificationQueue
            from agent_gateway.queue.backends.redis import RedisQueue

            self._notification_queue_backend = RedisNotificationQueue(url=config.redis_url)
            return RedisQueue(
                url=config.redis_url,
                stream_key=config.stream_key,
                consumer_group=config.consumer_group,
            )
        elif backend == "rabbitmq":
            from agent_gateway.notifications.queue_backends import RabbitMQNotificationQueue
            from agent_gateway.queue.backends.rabbitmq import RabbitMQQueue

            self._notification_queue_backend = RabbitMQNotificationQueue(url=config.rabbitmq_url)
            return RabbitMQQueue(url=config.rabbitmq_url, queue_name=config.queue_name)
        return None

    # --- Auth configuration (fluent API) ---

    def use_api_keys(
        self,
        keys: list[dict[str, Any]],
    ) -> Gateway:
        """Configure API key authentication.

        Args:
            keys: List of {"name": ..., "key": ..., "scopes": [...]} dicts.
                  Keys are hashed immediately; plaintext is not retained.
        """
        if self._started:
            raise RuntimeError("Cannot configure auth after gateway has started")
        from agent_gateway.auth.domain import ApiKeyRecord
        from agent_gateway.auth.providers.api_key import ApiKeyProvider, hash_api_key

        records = [
            ApiKeyRecord(
                id=str(i),
                name=k.get("name", f"key-{i}"),
                key_hash=hash_api_key(k["key"]),
                scopes=k.get("scopes", ["*"]),
            )
            for i, k in enumerate(keys)
        ]
        self._auth_provider = ApiKeyProvider(records)
        return self

    def use_oauth2(
        self,
        issuer: str,
        audience: str,
        jwks_uri: str | None = None,
        algorithms: list[str] | None = None,
        scope_claim: str = "scope",
    ) -> Gateway:
        """Configure OAuth2/OIDC JWT validation.

        Requires: pip install agent-gateway[oauth2]

        Args:
            issuer: Token issuer URL (e.g. "https://auth.example.com").
            audience: Expected audience claim.
            jwks_uri: JWKS endpoint URL. Defaults to {issuer}/.well-known/jwks.json.
            algorithms: Allowed signing algorithms. Defaults to ["RS256", "ES256"].
            scope_claim: JWT claim containing scopes. "scp" for Azure AD.
        """
        if self._started:
            raise RuntimeError("Cannot configure auth after gateway has started")
        from agent_gateway.auth.providers.oauth2 import OAuth2Provider

        self._auth_provider = OAuth2Provider(
            issuer=issuer,
            audience=audience,
            jwks_uri=jwks_uri,
            algorithms=algorithms,
            scope_claim=scope_claim,
        )
        self._oauth2_issuer = issuer
        return self

    def use_auth(self, provider: AuthProvider | None) -> Gateway:
        """Configure a custom auth provider, or None to disable auth.

        Args:
            provider: An AuthProvider implementation, or None to disable.
        """
        if self._started:
            raise RuntimeError("Cannot configure auth after gateway has started")
        self._auth_provider = provider
        return self

    # --- Notification configuration (fluent API) ---

    def use_slack_notifications(
        self,
        bot_token: str,
        default_channel: str = "#agent-alerts",
        templates_dir: Path | str | None = None,
    ) -> Gateway:
        """Configure Slack notifications.

        Requires: pip install agent-gateway[slack]

        Args:
            bot_token: Slack bot token (xoxb-...).
            default_channel: Default channel for notifications.
            templates_dir: Directory for custom Block Kit templates (.json.j2 files).
        """
        if self._started:
            raise RuntimeError("Cannot configure notifications after gateway has started")
        from agent_gateway.notifications.backends.slack import SlackBackend

        templates = Path(templates_dir) if templates_dir else None
        backend = SlackBackend(
            bot_token=bot_token,
            default_channel=default_channel,
            templates_dir=templates,
        )
        self._notification_backends.append(backend)
        return self

    def use_webhook_notifications(
        self,
        url: str,
        name: str = "default",
        secret: str = "",
        events: list[str] | None = None,
        payload_template: str | None = None,
    ) -> Gateway:
        """Add a webhook notification endpoint.

        Can be called multiple times to register multiple endpoints.
        Agents reference endpoints by name in AGENT.md frontmatter.

        Args:
            url: Webhook URL to POST to.
            name: Endpoint name (referenced in agent AGENT.md frontmatter).
            secret: HMAC-SHA256 signing secret.
            events: Event types to filter (empty = all events).
            payload_template: Jinja2 template for custom payloads.
        """
        if self._started:
            raise RuntimeError("Cannot configure notifications after gateway has started")
        from agent_gateway.notifications.backends.webhook import (
            WebhookBackend,
            WebhookEndpoint,
        )

        # Find or create WebhookBackend
        existing = next(
            (b for b in self._notification_backends if isinstance(b, WebhookBackend)),
            None,
        )
        endpoint = WebhookEndpoint(
            name=name,
            url=url,
            secret=secret,
            events=events or [],
            payload_template=payload_template,
        )
        if existing is not None:
            existing.add_endpoint(endpoint)
        else:
            backend = WebhookBackend(endpoints=[endpoint])
            self._notification_backends.append(backend)
        return self

    def use_notifications(self, backend: NotificationBackend | None) -> Gateway:
        """Register a custom notification backend, or None to disable all.

        Args:
            backend: A NotificationBackend implementation, or None to clear.
        """
        if self._started:
            raise RuntimeError("Cannot configure notifications after gateway has started")
        if backend is None:
            self._notification_backends.clear()
        else:
            self._notification_backends.append(backend)
        return self

    # --- Retriever configuration (fluent API) ---

    def use_retriever(self, name: str, retriever: ContextRetriever) -> Gateway:
        """Register a named context retriever.

        Agents reference retrievers by name in AGENT.md frontmatter
        via the ``retrievers:`` key. Retrievers are called during prompt
        assembly to inject dynamic context.

        Args:
            name: Unique name for this retriever (referenced in AGENT.md).
            retriever: A ContextRetriever implementation.

        Raises:
            RuntimeError: If called after gateway has started.
            ValueError: If a retriever with the same name is already registered.
        """
        if self._started:
            raise RuntimeError("Cannot configure retrievers after gateway has started")
        if name in self._pending_retrievers:
            raise ValueError(f"Retriever '{name}' is already registered")
        self._pending_retrievers[name] = retriever
        return self

    # --- MCP server configuration (fluent API) ---

    def add_mcp_server(
        self,
        name: str,
        transport: str,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        credentials: dict[str, Any] | None = None,
        token_provider: Any | None = None,
        enabled: bool = True,
    ) -> Gateway:
        """Register an MCP server programmatically (fluent API).

        Stores raw (unencrypted) values in the pending list. Encryption
        happens during startup so that AGENT_GATEWAY_SECRET_KEY does not
        need to be set at import time.

        Args:
            name: Unique server name.
            transport: 'stdio' or 'streamable_http'.
            command: Command for stdio transport.
            args: Arguments for stdio transport.
            env: Environment variables for stdio transport.
            url: URL for streamable_http transport.
            headers: Static HTTP headers.
            credentials: Credential dict (may contain auth_type for OAuth2).
            token_provider: Optional custom token provider. When provided, takes
                precedence over credentials-based auth. Implement the
                McpTokenProvider protocol to plug in any custom auth (Azure,
                AWS, etc.) without library changes.
            enabled: Whether the server is enabled.

        Raises:
            ValueError: If transport is not 'stdio' or 'streamable_http'.
        """
        valid_transports = ("stdio", "streamable_http")
        if transport not in valid_transports:
            raise ValueError(
                f"Invalid MCP transport '{transport}'. Must be one of: {valid_transports}"
            )
        self._pending_mcp_servers.append(
            {
                "name": name,
                "transport": transport,
                "command": command,
                "args": args,
                "env": env,
                "url": url,
                "headers": headers,
                "credentials": credentials,
                "token_provider": token_provider,
                "enabled": enabled,
            }
        )
        return self

    # --- Memory configuration (fluent API) ---

    def use_memory(self, backend: MemoryBackend) -> Gateway:
        """Configure a custom memory backend.

        Agents opt in to memory via ``memory.enabled: true`` in their AGENT.md
        frontmatter. Memory tools (recall, save, forget) are automatically
        registered for enabled agents.

        Args:
            backend: A MemoryBackend implementation (e.g. a pgvector-backed store).
        """
        if self._started:
            raise RuntimeError("Cannot configure memory after gateway has started")
        self._pending_memory_backend = backend
        return self

    def use_file_memory(self) -> Gateway:
        """Use the built-in file-based memory backend (MEMORY.md per agent).

        Zero infrastructure — memories are stored as structured markdown files
        in each agent's workspace directory. Human-readable and git-committable.

        Line cap is controlled by ``memory.max_memory_md_lines`` in gateway.yaml.
        """
        if self._started:
            raise RuntimeError("Cannot configure memory after gateway has started")
        from agent_gateway.memory.backends.file import FileMemoryBackend

        self._pending_memory_backend = FileMemoryBackend(
            workspace_root=Path(self._workspace_path),
        )
        return self

    # --- CORS configuration (fluent API) ---

    def use_cors(
        self,
        *,
        allow_origins: list[str] | None = None,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
        allow_credentials: bool = False,
        max_age: int = 3600,
    ) -> Gateway:
        """Enable CORS with the given settings.

        Example::

            gw = Gateway(workspace="workspace/")
            gw.use_cors(allow_origins=["https://myapp.com"])
        """
        if self._started:
            raise RuntimeError("Cannot configure CORS after gateway has started")
        kwargs: dict[str, Any] = {
            "enabled": True,
            "allow_credentials": allow_credentials,
            "max_age": max_age,
        }
        if allow_origins is not None:
            kwargs["allow_origins"] = allow_origins
        if allow_methods is not None:
            kwargs["allow_methods"] = allow_methods
        if allow_headers is not None:
            kwargs["allow_headers"] = allow_headers
        self._pending_cors_config = CorsConfig(**kwargs)
        return self

    # --- Rate limiting configuration (fluent API) ---

    def use_rate_limit(
        self,
        *,
        default_limit: str = "100/minute",
        storage_uri: str | None = None,
        trust_forwarded_for: bool = False,
    ) -> Gateway:
        """Enable rate limiting with the given settings.

        Example::

            gw = Gateway(workspace="workspace/")
            gw.use_rate_limit(default_limit="50/minute")
        """
        if self._started:
            raise RuntimeError("Cannot configure rate limiting after gateway has started")
        self._pending_rate_limit_config = RateLimitConfig(
            enabled=True,
            default_limit=default_limit,
            storage_uri=storage_uri,
            trust_forwarded_for=trust_forwarded_for,
        )
        return self

    # --- Security headers configuration (fluent API) ---

    def use_security_headers(
        self,
        *,
        enabled: bool = True,
        x_content_type_options: str = "nosniff",
        x_frame_options: str = "DENY",
        strict_transport_security: str = "max-age=31536000; includeSubDomains",
        content_security_policy: str = "default-src 'self'",
        referrer_policy: str = "strict-origin-when-cross-origin",
        dashboard_content_security_policy: str | None = None,
    ) -> Gateway:
        """Customize security headers.

        Security headers are enabled by default. Use this method to override
        individual header values or to disable them entirely.

        Example::

            gw = Gateway(workspace="workspace/")
            gw.use_security_headers(x_frame_options="SAMEORIGIN")
            gw.use_security_headers(enabled=False)  # disable
        """
        if self._started:
            raise RuntimeError("Cannot configure security headers after gateway has started")
        kwargs: dict[str, Any] = {
            "enabled": enabled,
            "x_content_type_options": x_content_type_options,
            "x_frame_options": x_frame_options,
            "strict_transport_security": strict_transport_security,
            "content_security_policy": content_security_policy,
            "referrer_policy": referrer_policy,
        }
        if dashboard_content_security_policy is not None:
            kwargs["dashboard_content_security_policy"] = dashboard_content_security_policy
        self._pending_security_config = SecurityConfig(**kwargs)
        return self

    # --- Dashboard configuration (fluent API) ---

    def use_dashboard(
        self,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        logo_url: str | None = None,
        favicon_url: str | None = None,
        auth_username: str | None = None,
        auth_password: str | None = None,
        theme: str | None = None,
        accent_color: str | None = None,
        primary_color: str | None = None,
        secondary_color: str | None = None,
        surface_color: str | None = None,
        sidebar_color: str | None = None,
        danger_color: str | None = None,
        oauth2_issuer: str | None = None,
        oauth2_client_id: str | None = None,
        oauth2_client_secret: str | None = None,
        oauth2_scopes: list[str] | None = None,
        login_button_text: str | None = None,
        admin_username: str | None = None,
        admin_password: str | None = None,
    ) -> Gateway:
        """Enable and configure the built-in web dashboard at /dashboard.

        The dashboard provides a UI for monitoring agents, executions, costs,
        and chatting with agents. It uses its own session-based authentication,
        independent of the API auth.

        Args:
            title: Dashboard page title (default: "Agent Gateway").
            subtitle: Dashboard subtitle shown below the title (default: "AI Control Plane").
            logo_url: URL of a logo image to display in the sidebar.
            favicon_url: URL of a favicon image for the browser tab.
            auth_username: Dashboard login username (default: "admin").
            auth_password: Dashboard login password. Empty = no password.
            theme: Color scheme — "light", "dark", or "auto" (default).
            accent_color: CSS hex color for the accent/primary color (legacy).
            primary_color: CSS hex color for buttons, links, active states.
            secondary_color: CSS hex color for secondary actions, muted text.
            surface_color: CSS hex color for card/panel backgrounds.
            sidebar_color: CSS hex color for sidebar background.
            danger_color: CSS hex color for error/destructive actions.
            login_button_text: Text for the SSO login button (default: "Sign in with SSO").
            admin_username: Separate admin account username (optional).
            admin_password: Separate admin account password (optional).
        """
        if self._started:
            raise RuntimeError("Cannot configure dashboard after gateway has started")
        self._pending_dashboard_overrides["enabled"] = True
        if title is not None:
            self._pending_dashboard_overrides["title"] = title
        if subtitle is not None:
            self._pending_dashboard_overrides["subtitle"] = subtitle
        if logo_url is not None:
            self._pending_dashboard_overrides["logo_url"] = logo_url
        if favicon_url is not None:
            self._pending_dashboard_overrides["favicon_url"] = favicon_url
        if auth_username is not None:
            self._pending_dashboard_overrides.setdefault("auth", {})["username"] = auth_username
        if auth_password is not None:
            self._pending_dashboard_overrides.setdefault("auth", {})["password"] = auth_password
        if admin_username is not None:
            self._pending_dashboard_overrides.setdefault("auth", {})["admin_username"] = (
                admin_username
            )
        if admin_password is not None:
            self._pending_dashboard_overrides.setdefault("auth", {})["admin_password"] = (
                admin_password
            )
        if login_button_text is not None:
            self._pending_dashboard_overrides.setdefault("auth", {})["login_button_text"] = (
                login_button_text
            )
        if theme is not None:
            self._pending_dashboard_overrides.setdefault("theme", {})["mode"] = theme
        if accent_color is not None:
            self._pending_dashboard_overrides.setdefault("theme", {})["accent_color"] = (
                accent_color
            )
        # Semantic color overrides
        color_map = {
            "primary": primary_color,
            "secondary": secondary_color,
            "surface": surface_color,
            "sidebar": sidebar_color,
            "danger": danger_color,
        }
        for key, val in color_map.items():
            if val is not None:
                colors = self._pending_dashboard_overrides.setdefault("theme", {}).setdefault(
                    "colors", {}
                )
                colors[key] = val
        if oauth2_issuer is not None or oauth2_client_id is not None:
            oauth2_dict = self._pending_dashboard_overrides.setdefault("auth", {}).setdefault(
                "oauth2", {}
            )
            if oauth2_issuer is not None:
                oauth2_dict["issuer"] = oauth2_issuer
            if oauth2_client_id is not None:
                oauth2_dict["client_id"] = oauth2_client_id
            if oauth2_client_secret is not None:
                oauth2_dict["client_secret"] = oauth2_client_secret
            if oauth2_scopes is not None:
                oauth2_dict["scopes"] = oauth2_scopes
        return self

    def _init_notifications_from_config(self, config: NotificationsConfig) -> None:
        """Create notification backends from gateway.yaml config."""
        if config.slack.enabled and config.slack.bot_token:
            try:
                from agent_gateway.notifications.backends.slack import SlackBackend

                backend = SlackBackend(
                    bot_token=config.slack.bot_token,
                    default_channel=config.slack.default_channel,
                )
                self._notification_engine.register(backend)
            except ImportError:
                logger.warning("Slack notifications enabled but slack extra not installed")

        if config.webhooks:
            from agent_gateway.notifications.backends.webhook import (
                WebhookBackend,
                WebhookEndpoint,
            )

            endpoints = [
                WebhookEndpoint(
                    name=wh.name,
                    url=wh.url,
                    secret=wh.secret or config.webhook_secret,
                    events=wh.events,
                    payload_template=wh.payload_template,
                )
                for wh in config.webhooks
            ]
            wh_backend = WebhookBackend(
                endpoints=endpoints,
                default_secret=config.webhook_secret,
            )
            self._notification_engine.register(wh_backend)

    def _resolve_auth_provider(self) -> AuthProvider | None:
        """Resolve the auth provider from fluent API, constructor, or config.

        Precedence: fluent API > constructor auth= param > gateway.yaml config.
        """
        # 1. Fluent API (use_api_keys, use_oauth2, use_auth)
        if self._auth_provider is not _AUTH_NOT_SET:
            if self._auth_provider is None:
                return None  # explicitly disabled via use_auth(None)
            assert isinstance(self._auth_provider, AuthProvider)
            return self._auth_provider

        # 2. Constructor param
        if self._auth_setting is False:
            return None
        if isinstance(self._auth_setting, bool):
            # auth=True — fall through to config
            pass
        elif isinstance(self._auth_setting, AuthProvider):
            self._auth_provider = self._auth_setting
            return self._auth_provider
        elif callable(self._auth_setting):
            from agent_gateway.auth import CallableAuthProvider

            self._auth_provider = CallableAuthProvider(self._auth_setting)
            return self._auth_provider

        # 3. Config-based
        if self._config is None:
            return None
        auth_cfg = self._config.auth
        if not auth_cfg.enabled or auth_cfg.mode == "none":
            return None

        if auth_cfg.mode == "api_key" and auth_cfg.api_keys:
            from agent_gateway.auth.domain import ApiKeyRecord
            from agent_gateway.auth.providers.api_key import ApiKeyProvider, hash_api_key

            records = [
                ApiKeyRecord(
                    id=str(i),
                    name=k.name,
                    key_hash=hash_api_key(k.key),
                    scopes=k.scopes,
                )
                for i, k in enumerate(auth_cfg.api_keys)
            ]
            self._auth_provider = ApiKeyProvider(records)
            return self._auth_provider

        if auth_cfg.mode == "oauth2" and auth_cfg.oauth2:
            from agent_gateway.auth.providers.oauth2 import OAuth2Provider

            o = auth_cfg.oauth2
            self._auth_provider = OAuth2Provider(
                issuer=o.issuer,
                audience=o.audience,
                jwks_uri=o.jwks_uri,
                algorithms=o.algorithms,
                scope_claim=o.scope_claim,
                clock_skew_seconds=o.clock_skew_seconds,
            )
            self._oauth2_issuer = o.issuer
            return self._auth_provider

        if auth_cfg.mode == "composite":
            from agent_gateway.auth.providers.composite import CompositeProvider

            providers: list[AuthProvider] = []
            if auth_cfg.api_keys:
                from agent_gateway.auth.domain import ApiKeyRecord as _AKR
                from agent_gateway.auth.providers.api_key import (
                    ApiKeyProvider,
                    hash_api_key,
                )

                records = [
                    _AKR(
                        id=str(i),
                        name=k.name,
                        key_hash=hash_api_key(k.key),
                        scopes=k.scopes,
                    )
                    for i, k in enumerate(auth_cfg.api_keys)
                ]
                providers.append(ApiKeyProvider(records))
            if auth_cfg.oauth2:
                from agent_gateway.auth.providers.oauth2 import OAuth2Provider as _O2

                o = auth_cfg.oauth2
                providers.append(
                    _O2(
                        issuer=o.issuer,
                        audience=o.audience,
                        jwks_uri=o.jwks_uri,
                        algorithms=o.algorithms,
                        scope_claim=o.scope_claim,
                        clock_skew_seconds=o.clock_skew_seconds,
                    )
                )
                self._oauth2_issuer = o.issuer
            if providers:
                self._auth_provider = CompositeProvider(providers)
                return self._auth_provider

        return None

    async def _inject_openapi_security_scheme(self) -> None:
        """Add security scheme(s) to the OpenAPI spec for Swagger UI Authorize button.

        - API key auth → HTTP Bearer scheme
        - OAuth2 auth → OAuth2 Authorization Code flow (via OIDC discovery)
        - Both present (composite) → both schemes
        """
        schemes: dict[str, dict[str, Any]] = {}
        security: list[dict[str, list[str]]] = []

        # Always add Bearer scheme — the auth middleware accepts Bearer tokens
        # regardless of whether it's API key or OAuth2 JWT validation.
        schemes["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "API key or JWT access token",
        }
        security.append({"bearerAuth": []})

        # If OAuth2 issuer is configured, also add the OAuth2 flow so Swagger UI
        # can perform interactive login (authorization code + token exchange).
        if self._oauth2_issuer:
            import httpx

            discovery_url = f"{self._oauth2_issuer.rstrip('/')}/.well-known/openid-configuration"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(discovery_url)
                    resp.raise_for_status()
                    discovery = resp.json()
                auth_url = discovery["authorization_endpoint"]
                token_url = discovery["token_endpoint"]
                schemes["oauth2"] = {
                    "type": "oauth2",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": auth_url,
                            "tokenUrl": token_url,
                            "scopes": {"openid": "OpenID Connect"},
                        }
                    },
                }
                security.append({"oauth2": ["openid"]})
            except Exception:
                logger.warning(
                    "Failed to fetch OIDC discovery from %s; OAuth2 Swagger login "
                    "will not be available (Bearer auth still works)",
                    discovery_url,
                )

        # Patch the openapi() method to inject the security schemes.
        # Clear any cached schema so the next call regenerates with our patch.
        self.openapi_schema = None
        original_openapi = self.openapi

        def patched_openapi() -> dict[str, Any]:
            result = original_openapi()
            components = result.setdefault("components", {})
            security_schemes = components.setdefault("securitySchemes", {})
            security_schemes.update(schemes)
            # Apply globally so all endpoints show the lock icon
            if "security" not in result:
                result["security"] = security
            return result

        self.openapi = patched_openapi  # type: ignore[method-assign]

    def _build_delegation_tool(self, workspace: WorkspaceState) -> CodeTool:
        """Build the delegate_to_agent CodeTool for the given workspace."""
        from agent_gateway.engine.delegation import run_delegation

        agent_ids = list(workspace.agents.keys())

        async def _delegate_to_agent(
            agent_id: str,
            message: str,
            input: dict[str, Any] | None = None,
            context: Any = None,
        ) -> str:
            """Delegate a task to another agent and get their result."""
            from agent_gateway.engine.models import ToolContext

            ctx: ToolContext = context
            return await run_delegation(
                self,
                caller_agent_id=ctx.agent_id,
                delegates_to=ctx.delegates_to,
                execution_id=ctx.execution_id,
                root_execution_id=ctx.root_execution_id or ctx.execution_id,
                delegation_depth=ctx.delegation_depth,
                user_id=ctx.caller_identity,
                agent_id=agent_id,
                message=message,
                input=input,
            )

        return CodeTool(
            name="delegate_to_agent",
            description=(
                "Delegate a task to another agent and get their result. "
                "Use this to hand off specialized work to another agent. "
                f"Available agents: {', '.join(agent_ids)}"
            ),
            fn=_delegate_to_agent,
            parameters_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "The ID of the agent to delegate to. "
                            f"Available agents: {', '.join(agent_ids)}"
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": "The task/message to send to the target agent.",
                    },
                    "input": {
                        "type": "object",
                        "description": "Optional structured input for the target agent.",
                    },
                },
                "required": ["agent_id", "message"],
            },
            allowed_agents=None,
        )

    def _apply_pending_input_schemas(self, workspace: WorkspaceState) -> None:
        """Apply code-registered input schemas to workspace agents."""
        if not self._pending_input_schemas:
            return

        from agent_gateway.engine.input import resolve_input_schema

        for agent_id, schema in self._pending_input_schemas.items():
            agent = workspace.agents.get(agent_id)
            if agent is None:
                logger.warning(
                    "set_input_schema: agent '%s' not found in workspace, skipping",
                    agent_id,
                )
                continue
            json_schema, _ = resolve_input_schema(schema)
            agent.input_schema = json_schema

    def _backend_from_config(self, config: PersistenceConfig) -> PersistenceBackend | None:
        """Create a backend from YAML/env configuration (backward compat)."""
        if config.backend == "sqlite":
            from agent_gateway.persistence.backends.sqlite import SqliteBackend

            # Extract path from URL: "sqlite+aiosqlite:///foo.db" -> "foo.db"
            path = config.url.split("///", 1)[-1] if "///" in config.url else "agent_gateway.db"
            return SqliteBackend(path=path, table_prefix=config.table_prefix)
        elif config.backend in ("postgres", "postgresql"):
            from agent_gateway.persistence.backends.postgres import PostgresBackend

            return PostgresBackend(
                url=config.url,
                schema=config.db_schema,
                table_prefix=config.table_prefix,
            )
        return None

    def _maybe_init_dashboard(self) -> None:
        """Enable the dashboard if configured (called during startup)."""
        if self._config is None:
            return

        # Merge fluent API overrides into config
        dash = self._config.dashboard
        overrides = self._pending_dashboard_overrides
        if overrides:
            from agent_gateway.config import (
                DashboardAuthConfig,
                DashboardConfig,
                DashboardOAuth2Config,
                DashboardThemeConfig,
            )

            auth_overrides = overrides.pop("auth", {})
            theme_overrides = overrides.pop("theme", {})

            # Handle nested oauth2 config
            oauth2_overrides = auth_overrides.pop("oauth2", None)
            existing_auth = dash.auth.model_dump()
            merged_auth = {**existing_auth, **auth_overrides}

            if oauth2_overrides:
                if existing_auth.get("oauth2"):
                    merged_oauth2 = {**existing_auth["oauth2"], **oauth2_overrides}
                else:
                    merged_oauth2 = oauth2_overrides
                merged_auth["oauth2"] = DashboardOAuth2Config(**merged_oauth2)
            else:
                merged_auth.pop("oauth2", None)
                if existing_auth.get("oauth2"):
                    merged_auth["oauth2"] = DashboardOAuth2Config(**existing_auth["oauth2"])

            auth = DashboardAuthConfig(**merged_auth)
            # Handle nested colors config
            colors_overrides = theme_overrides.pop("colors", None)
            existing_theme = dash.theme.model_dump()
            merged_theme = {**existing_theme, **theme_overrides}
            if colors_overrides:
                from agent_gateway.config import DashboardColorConfig

                existing_colors = existing_theme.get("colors", {})
                merged_theme["colors"] = DashboardColorConfig(
                    **{**existing_colors, **colors_overrides}
                )
            theme = DashboardThemeConfig(**merged_theme)
            dash = DashboardConfig(
                **{**dash.model_dump(), **overrides, "auth": auth, "theme": theme}
            )
            self._config = self._config.model_copy(update={"dashboard": dash})

        if not self._config.dashboard.enabled:
            return

        dash_config = self._config.dashboard

        # Validate mutually exclusive auth methods
        from agent_gateway.exceptions import ConfigError

        if dash_config.auth.oauth2 and dash_config.auth.password:
            raise ConfigError(
                "Dashboard auth: oauth2 and password are mutually exclusive. "
                "Set either dashboard.auth.password or dashboard.auth.oauth2, not both."
            )

        if dash_config.auth.oauth2 and not dash_config.auth.oauth2.client_secret:
            raise ConfigError(
                "Dashboard OAuth2 requires a client_secret (confidential client only)."
            )

        # Warn if no password set (only for password auth mode)
        if (
            dash_config.auth.enabled
            and not dash_config.auth.oauth2
            and not dash_config.auth.password
        ):
            logger.warning(
                "Dashboard is enabled with no password set. "
                "Set dashboard.auth.password in gateway.yaml or use_dashboard(auth_password=...)."
            )

        # Require admin credentials when password auth is enabled
        if (
            dash_config.auth.enabled
            and not dash_config.auth.oauth2
            and (not dash_config.auth.admin_username or not dash_config.auth.admin_password)
        ):
            raise ConfigError(
                "Dashboard requires admin_username and admin_password when password auth "
                "is enabled. Set both to define the super-admin account."
            )

        # Generate session secret if not set
        import secrets as _secrets

        session_secret = dash_config.auth.session_secret or _secrets.token_hex(32)

        # Add SessionMiddleware
        try:
            from starlette.middleware.sessions import SessionMiddleware

            if self.middleware_stack is not None:
                self.middleware_stack = SessionMiddleware(
                    app=self.middleware_stack,
                    secret_key=session_secret,
                    session_cookie="agw_dashboard_session",
                    max_age=86400,
                    https_only=False,
                    same_site="lax",
                )
            else:
                self.add_middleware(
                    SessionMiddleware,
                    secret_key=session_secret,
                    session_cookie="agw_dashboard_session",
                    max_age=86400,
                    https_only=False,
                    same_site="lax",
                )
        except ImportError:
            logger.error(
                "SessionMiddleware requires 'itsdangerous'. Install with: pip install itsdangerous"
            )
            return

        # Create OAuth2 discovery client if needed
        oauth2_config = dash_config.auth.oauth2
        discovery_client = None
        if oauth2_config:
            from agent_gateway.dashboard.oauth2 import OIDCDiscoveryClient

            discovery_client = OIDCDiscoveryClient(oauth2_config.issuer)
            self._dashboard_discovery_client = discovery_client

            async def _close_discovery() -> None:
                if discovery_client is not None:
                    await discovery_client.close()

            # Register shutdown handler via the hooks system
            self._hooks.register("gateway.shutdown", _close_discovery)

        # Register dashboard routes
        try:
            from agent_gateway.dashboard.router import register_dashboard

            register_dashboard(
                self,
                dash_config,
                oauth2_config=oauth2_config,
                discovery_client=discovery_client,
                mount_prefix=self._mount_prefix,
            )
            if oauth2_config:
                logger.info("Dashboard enabled at /dashboard (OAuth2/SSO)")
            else:
                logger.info(
                    "Dashboard enabled at /dashboard (user: %s)", dash_config.auth.username
                )
        except ImportError as e:
            logger.error("Failed to load dashboard (missing dependencies?): %s", e)

    def _register_routes(self) -> None:
        """Mount all /v1/ API routes."""
        from agent_gateway.api.routes.base import GatewayAPIRoute
        from agent_gateway.api.routes.chat import router as chat_router
        from agent_gateway.api.routes.executions import router as executions_router
        from agent_gateway.api.routes.health import router as health_router
        from agent_gateway.api.routes.introspection import router as introspection_router
        from agent_gateway.api.routes.invoke import router as invoke_router
        from agent_gateway.api.routes.mcp_servers import router as mcp_servers_router
        from agent_gateway.api.routes.notifications import router as notifications_router
        from agent_gateway.api.routes.schedules import router as schedules_router
        from agent_gateway.api.routes.user_config import router as user_config_router

        v1 = APIRouter(prefix="/v1", route_class=GatewayAPIRoute)
        v1.include_router(health_router)
        v1.include_router(invoke_router)
        v1.include_router(chat_router)
        v1.include_router(executions_router)
        v1.include_router(introspection_router)
        v1.include_router(schedules_router)
        v1.include_router(user_config_router)
        v1.include_router(notifications_router)
        v1.include_router(mcp_servers_router)

        self.include_router(v1)

    async def reload(self) -> None:
        """Reload workspace from disk and rebuild registry (atomic snapshot swap)."""
        async with self._reload_lock:
            ws_path = Path(self._workspace_path)
            retriever_names = frozenset(self._pending_retrievers.keys())
            new_workspace = load_workspace(ws_path, retriever_names=retriever_names)

            new_registry = ToolRegistry()
            new_registry.register_file_tools(new_workspace.tools)
            for code_tool in self._pending_tools:
                new_registry.register_code_tool(code_tool)

            # Re-register MCP tools after reload
            if self._mcp_manager is not None:
                from agent_gateway.mcp.manager import compute_server_to_agents

                server_to_agents = compute_server_to_agents(new_workspace)
                all_mcp_tools = self._mcp_manager.get_all_tools()
                for server_name, tools in all_mcp_tools.items():
                    allowed = server_to_agents.get(server_name)
                    new_registry.register_mcp_tools(tools, allowed_agents=allowed)

            new_engine: ExecutionEngine | None = None
            if self._llm_client and self._config:
                new_engine = ExecutionEngine(
                    llm_client=self._llm_client,
                    tool_registry=new_registry,
                    config=self._config,
                    hooks=self._hooks,
                    retriever_registry=self._retriever_registry,
                    execution_repo=self._execution_repo,
                    mcp_manager=self._mcp_manager,
                )

            # Re-register memory tools for agents that have memory enabled
            if self._memory_manager is not None:
                memory_agents = [
                    aid
                    for aid, a in new_workspace.agents.items()
                    if a.memory_config and a.memory_config.enabled
                ]
                if memory_agents:
                    from agent_gateway.memory.tools import make_memory_tools

                    mem_tools = make_memory_tools(self._memory_manager)
                    for tool_def in mem_tools:
                        code_tool = CodeTool(
                            name=tool_def["name"],
                            description=tool_def["description"],
                            fn=tool_def["func"],
                            parameters_schema=tool_def["parameters"],
                            allowed_agents=memory_agents,
                        )
                        new_registry.register_code_tool(code_tool)

            # Re-register delegation tool when workspace has 2+ agents
            if len(new_workspace.agents) >= 2:
                delegation_tool = self._build_delegation_tool(new_workspace)
                new_registry.register_code_tool(delegation_tool)

            # Re-apply code-registered input schemas
            self._apply_pending_input_schemas(new_workspace)

            # Single atomic reference swap
            self._snapshot = WorkspaceSnapshot(
                workspace=new_workspace,
                tool_registry=new_registry,
                engine=new_engine,
                retriever_registry=self._retriever_registry,
                context_retrieval_config=self._config.context_retrieval if self._config else None,
            )

            logger.info("Workspace reloaded: %d agents", len(new_workspace.agents))

    async def _reload_workspace(self) -> None:
        """Alias for backward compatibility."""
        await self.reload()

    def fire_notifications(
        self,
        *,
        execution_id: str,
        agent_id: str,
        status: str,
        message: str,
        config: Any,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        usage: dict[str, Any] | None = None,
        duration_ms: int = 0,
        input: dict[str, Any] | None = None,
    ) -> None:
        """Fire notifications via queue (if available) or as a background task.

        Never raises — errors are logged and swallowed.
        Delivery results are persisted to the notification_log table.
        """
        if not self._notification_engine.has_backends or not config:
            return

        from agent_gateway.notifications.models import (
            AgentNotificationConfig,
            NotificationTarget,
        )

        # Determine which targets will be notified for logging purposes
        _event_routing: dict[str, str] = {
            "completed": "on_complete",
            "failed": "on_error",
            "timeout": "on_timeout",
            "error": "on_error",
            "cancelled": "on_error",
        }
        attr_name = _event_routing.get(status)
        if isinstance(config, AgentNotificationConfig):
            targets: list[NotificationTarget] = getattr(config, attr_name, []) if attr_name else []
        else:
            targets = []

        if self._notification_queue is not None:
            # Enqueue for durable delivery via NotificationWorker
            job = build_notification_job(
                job_id=str(uuid.uuid4()),
                execution_id=execution_id,
                agent_id=agent_id,
                status=status,
                message=message,
                config=config,
                result=result,
                error=error,
                usage=usage,
                duration_ms=duration_ms,
                input=input,
            )
            task = asyncio.create_task(self._notification_queue.enqueue(job))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            # Delivery records are created by NotificationWorker after processing
        else:
            # Fire-and-forget fallback (no queue configured)
            event = build_notification_event(
                execution_id=execution_id,
                agent_id=agent_id,
                status=status,
                message=message,
                result=result,
                error=error,
                usage=usage,
                duration_ms=duration_ms,
                input=input,
            )
            task = asyncio.create_task(
                self._notify_and_log(event, config, execution_id, agent_id, targets)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _notify_and_log(
        self,
        event: Any,
        config: Any,
        execution_id: str,
        agent_id: str,
        targets: list[Any],
    ) -> None:
        """Dispatch notifications and log delivery results."""
        from datetime import UTC, datetime

        try:
            await self._notification_engine.notify(event, config)
            # If notify() returns without error, all targets were attempted
            for t in targets:
                self._log_notification_delivery(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    event_type=event.type,
                    channel=t.channel,
                    target=sanitize_target(t.target or t.url or ""),
                    delivery_status="delivered",
                    attempts=1,
                    last_error=None,
                    delivered_at=datetime.now(UTC),
                )
        except Exception as exc:
            logger.warning(
                "Notification delivery failed for execution %s: %s",
                execution_id,
                exc,
                exc_info=True,
            )
            for t in targets:
                self._log_notification_delivery(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    event_type=event.type,
                    channel=t.channel,
                    target=sanitize_target(t.target or t.url or ""),
                    delivery_status="failed",
                    attempts=1,
                    last_error=str(exc),
                )

    def _log_notification_delivery(
        self,
        *,
        execution_id: str,
        agent_id: str,
        event_type: str,
        channel: str,
        target: str,
        delivery_status: str,
        attempts: int,
        last_error: str | None,
        delivered_at: datetime | None = None,
    ) -> None:
        """Create a background task to persist a notification delivery record."""
        record = NotificationDeliveryRecord(
            execution_id=execution_id,
            agent_id=agent_id,
            event_type=event_type,
            channel=channel,
            target=target,
            status=delivery_status,
            attempts=attempts,
            last_error=last_error,
            delivered_at=delivered_at,
        )
        task = asyncio.create_task(self._persist_notification_record(record))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _persist_notification_record(self, record: NotificationDeliveryRecord) -> None:
        """Persist a notification delivery record. Never raises."""
        try:
            await self._notification_repo.create(record)
        except Exception:
            logger.warning(
                "Failed to persist notification delivery record for execution %s",
                record.execution_id,
                exc_info=True,
            )

    async def _get_memory_block(
        self, agent_id: str, message: str, memory_config: Any, user_id: str | None = None
    ) -> str:
        """Fetch the memory context block for an agent, returning empty string on failure."""
        if self._memory_manager is None or not memory_config or not memory_config.enabled:
            return ""
        try:
            block = await self._memory_manager.get_context_block(
                agent_id,
                query=message,
                max_chars=memory_config.max_injected_chars,
                user_id=user_id,
            )

            # Prepend user profile info so agents can address users by name
            if user_id is not None:
                try:
                    profile = await self._user_repo.get(user_id)
                    if profile is not None and profile.display_name:
                        user_line = f"### Current User\nName: {profile.display_name}"
                        block = f"{user_line}\n\n{block}" if block else user_line
                except Exception:
                    pass  # Non-critical — don't fail the whole memory block

            return block
        except Exception:
            logger.warning("Failed to fetch memory for agent '%s'", agent_id, exc_info=True)
            return ""

    def _derive_user_id(self, auth: Any | None) -> str | None:
        """Derive a user_id from an AuthResult. Returns None for shared mode."""
        if auth is None:
            return None
        if not getattr(auth, "authenticated", False):
            return None
        method = getattr(auth, "auth_method", "")
        if method == "oauth2":
            return getattr(auth, "subject", None)
        return None

    @staticmethod
    def _decrypt_user_secrets(encrypted_secrets: dict[str, Any]) -> dict[str, str]:
        """Decrypt user secrets from a UserAgentConfig."""
        if not encrypted_secrets:
            return {}
        from agent_gateway.secrets import decrypt_value

        result: dict[str, str] = {}
        for key, ciphertext in encrypted_secrets.items():
            try:
                result[key] = decrypt_value(str(ciphertext))
            except ValueError:
                logger.warning("Failed to decrypt secret '%s', skipping", key)
        return result

    async def _ensure_user_profile(self, auth: Any | None) -> None:
        """Auto-create or update user profile from auth claims."""
        if auth is None or not getattr(auth, "authenticated", False):
            return
        user_id = self._derive_user_id(auth)
        if user_id is None:
            return

        from datetime import UTC, datetime

        from agent_gateway.persistence.domain import UserProfile

        claims = getattr(auth, "claims", {})
        now = datetime.now(UTC)
        profile = UserProfile(
            user_id=user_id,
            display_name=claims.get("name") or claims.get("preferred_username"),
            email=claims.get("email"),
            metadata={k: v for k, v in claims.items() if k not in ("name", "email", "sub")},
            first_seen_at=now,
            last_seen_at=now,
        )
        try:
            await self._user_repo.upsert(profile)
        except Exception:
            logger.warning("Failed to upsert user profile for '%s'", user_id, exc_info=True)

    def _persist_conversation_messages(
        self,
        session: ChatSession,
        user_message: str,
        assistant_text: str | None,
    ) -> None:
        """Async write-behind: persist conversation and messages to the database."""
        from datetime import UTC, datetime

        from agent_gateway.persistence.domain import (
            ConversationMessage,
            ConversationRecord,
        )

        conv_repo = self._conversation_repo
        now = datetime.now(UTC)

        async def _persist() -> None:
            # Ensure conversation record exists
            existing = await conv_repo.get(session.session_id)
            if existing is None:
                record = ConversationRecord(
                    conversation_id=session.session_id,
                    agent_id=session.agent_id,
                    user_id=session.user_id,
                    message_count=0,
                    created_at=now,
                    updated_at=now,
                )
                await conv_repo.create(record)

            # Persist user message
            await conv_repo.add_message(
                ConversationMessage(
                    message_id=uuid.uuid4().hex[:16],
                    conversation_id=session.session_id,
                    role="user",
                    content=user_message,
                    created_at=now,
                )
            )

            # Persist assistant message
            if assistant_text:
                await conv_repo.add_message(
                    ConversationMessage(
                        message_id=uuid.uuid4().hex[:16],
                        conversation_id=session.session_id,
                        role="assistant",
                        content=assistant_text,
                        created_at=now,
                    )
                )

            # Update conversation metadata
            msg_count = len(session.messages)
            existing_record = await conv_repo.get(session.session_id)
            if existing_record is not None:
                existing_record.message_count = msg_count
                existing_record.updated_at = now
                await conv_repo.update(existing_record)

        task = asyncio.create_task(
            _persist(),
            name=f"persist-conv-{session.session_id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _ensure_dashboard_user_profile(self, dashboard_user: Any) -> None:
        """Create/update a user profile from a DashboardUser (used by dashboard chat)."""
        username = getattr(dashboard_user, "username", None)
        if not username or username == "anonymous":
            return
        from datetime import UTC, datetime

        from agent_gateway.persistence.domain import UserProfile

        now = datetime.now(UTC)
        profile = UserProfile(
            user_id=username,
            display_name=getattr(dashboard_user, "display_name", "") or username,
            first_seen_at=now,
            last_seen_at=now,
        )
        try:
            await self._user_repo.upsert(profile)
        except Exception:
            logger.warning("Failed to upsert dashboard user profile for '%s'", username)

    def _trigger_memory_extraction(
        self,
        agent_id: str,
        user_message: str,
        assistant_text: str,
        user_id: str | None = None,
    ) -> None:
        """Fire-and-forget memory extraction with debouncing."""
        if self._memory_manager is None or self._llm_client is None:
            return

        now = time.monotonic()
        debounce_key = f"{agent_id}:{user_id or ''}"
        last_extraction = self._extraction_cooldowns.get(debounce_key, 0.0)
        if now - last_extraction < self._extraction_debounce:
            return

        self._extraction_cooldowns[debounce_key] = now
        recent_messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_text},
        ]
        mm = self._memory_manager
        _uid = user_id

        async def _extract() -> None:
            await mm.extract_memories(agent_id, recent_messages, user_id=_uid)
            await mm.compact_memories(agent_id, user_id=_uid)

        task = asyncio.create_task(
            _extract(),
            name=f"memory-extract-{agent_id}-{user_id or 'global'}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def invoke(
        self,
        agent_id: str,
        message: str,
        input: dict[str, Any] | None = None,
        options: ExecutionOptions | None = None,
        auth: Any | None = None,
        parent_execution_id: str | None = None,
        root_execution_id: str | None = None,
        delegation_depth: int = 0,
    ) -> ExecutionResult:
        """Invoke an agent programmatically (bypasses HTTP).

        Args:
            agent_id: The agent to invoke.
            message: The user message.
            input: Optional input dict.
            options: Optional execution options.
            auth: Optional AuthResult from the request (for user-scoped operations).
            parent_execution_id: ID of the parent execution (for delegated calls).
            root_execution_id: ID of the root execution in a delegation tree.
            delegation_depth: Current depth in the delegation tree.

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

        # Validate input against agent's input_schema
        if agent.input_schema:
            from agent_gateway.engine.input import validate_input
            from agent_gateway.exceptions import InputValidationError

            errors = validate_input(input, agent.input_schema)
            if errors:
                raise InputValidationError(
                    f"Input validation failed for agent '{agent_id}': {'; '.join(errors)}",
                    errors=errors,
                )

        # Load per-user agent config for personal agents
        user_id = self._derive_user_id(auth) if auth else None
        user_instructions: str | None = None
        user_secrets: dict[str, str] = {}
        user_config_values: dict[str, Any] = {}

        if agent.scope == "personal" and user_id:
            user_agent_config = await self._user_agent_config_repo.get(user_id, agent_id)
            if user_agent_config is None or not user_agent_config.setup_completed:
                raise ValueError(
                    f"Agent '{agent_id}' requires setup. "
                    f"Configure via POST /v1/agents/{agent_id}/config"
                )
            user_instructions = user_agent_config.instructions
            user_config_values = user_agent_config.config_values
            user_secrets = self._decrypt_user_secrets(user_agent_config.encrypted_secrets)
        elif agent.scope == "personal" and not user_id:
            raise ValueError(f"Agent '{agent_id}' is a personal agent and requires authentication")

        # Schedule-specific instructions (injected by scheduler engine via input dict)
        schedule_instructions: str | None = input.get("_schedule_instructions") if input else None

        memory_block = await self._get_memory_block(agent_id, message, agent.memory_config)

        execution_id = str(uuid.uuid4())
        handle = ExecutionHandle(execution_id=execution_id)
        self._execution_handles[execution_id] = handle

        # Resolve root execution ID for delegation tree
        effective_root_id = root_execution_id or execution_id

        # Persist execution record for delegated calls
        if parent_execution_id is not None:
            from datetime import UTC, datetime

            from agent_gateway.persistence.domain import ExecutionRecord

            record = ExecutionRecord(
                id=execution_id,
                agent_id=agent_id,
                status="running",
                message=message,
                input=input or None,
                parent_execution_id=parent_execution_id,
                root_execution_id=effective_root_id,
                delegation_depth=delegation_depth,
                started_at=datetime.now(UTC),
            )
            await self._execution_repo.create(record)

        try:
            result = await snapshot.engine.execute(
                agent=agent,
                message=message,
                workspace=snapshot.workspace,
                input=input,
                options=options,
                handle=handle,
                tool_executor=execute_tool,
                memory_block=memory_block,
                user_instructions=user_instructions,
                schedule_instructions=schedule_instructions,
                caller_identity=user_id,
                user_secrets=user_secrets,
                user_config=user_config_values,
                parent_execution_id=parent_execution_id,
                root_execution_id=effective_root_id,
                delegation_depth=delegation_depth,
                delegates_to=agent.delegates_to,
            )

            # Fire notifications
            self.fire_notifications(
                execution_id=execution_id,
                agent_id=agent_id,
                status=result.stop_reason.value,
                message=message,
                config=agent.notifications,
                result=result.to_dict() if result.raw_text else None,
                usage=result.usage.to_dict() if result.usage else None,
                input=input,
            )

            # Fire user-schedule notifications (embedded in input by scheduler)
            if input and input.get("_notify_config"):
                from agent_gateway.notifications.models import AgentNotificationConfig

                user_notify = AgentNotificationConfig.from_dict(input["_notify_config"])
                self.fire_notifications(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    status=result.stop_reason.value,
                    message=message,
                    config=user_notify,
                    result=result.to_dict() if result.raw_text else None,
                    usage=result.usage.to_dict() if result.usage else None,
                    input=input,
                )

            # Update delegated execution record with result
            if parent_execution_id is not None:
                from datetime import UTC, datetime

                status = "completed" if result.stop_reason.value == "completed" else "failed"
                await self._execution_repo.update_status(
                    execution_id,
                    status,
                    result=result.to_dict(),
                    usage=result.usage.to_dict(),
                    completed_at=datetime.now(UTC),
                )

            return result
        finally:
            self._execution_handles.pop(execution_id, None)

    async def chat(
        self,
        agent_id: str,
        message: str,
        session_id: str | None = None,
        input: dict[str, Any] | None = None,
        options: ExecutionOptions | None = None,
        auth: Any | None = None,
    ) -> tuple[str, ExecutionResult]:
        """Send a chat message programmatically (bypasses HTTP).

        Args:
            agent_id: The agent to chat with.
            message: The user message.
            session_id: Optional existing session ID. Creates new session if None.
            input: Optional input dict.
            options: Optional execution options.
            auth: Optional AuthResult from the request (for user-scoped operations).

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

        # Derive user context from auth
        user_id = self._derive_user_id(auth)

        # Auto-create/update user profile (fire-and-forget)
        if user_id is not None:
            profile_task = asyncio.create_task(
                self._ensure_user_profile(auth),
                name=f"user-profile-{user_id}",
            )
            self._background_tasks.add(profile_task)
            profile_task.add_done_callback(self._background_tasks.discard)

        # Load per-user agent config for personal agents
        user_instructions: str | None = None
        user_secrets: dict[str, str] = {}
        user_config_values: dict[str, Any] = {}

        if agent.scope == "personal" and user_id:
            user_agent_config = await self._user_agent_config_repo.get(user_id, agent_id)
            if user_agent_config is None or not user_agent_config.setup_completed:
                raise ValueError(
                    f"Agent '{agent_id}' requires setup. "
                    f"Configure via POST /v1/agents/{agent_id}/config"
                )
            user_instructions = user_agent_config.instructions
            user_config_values = user_agent_config.config_values
            user_secrets = self._decrypt_user_secrets(user_agent_config.encrypted_secrets)
        elif agent.scope == "personal" and not user_id:
            raise ValueError(f"Agent '{agent_id}' is a personal agent and requires authentication")

        # Get or create session
        if session_id:
            session = await self._get_or_restore_session(session_id)
            if session is None:
                raise ValueError(f"Session '{session_id}' not found")
            if session.agent_id != agent_id:
                raise ValueError(
                    f"Session '{session_id}' belongs to agent "
                    f"'{session.agent_id}', not '{agent_id}'"
                )
            # Enforce session ownership in multi-user mode
            if user_id is not None and session.user_id is not None and session.user_id != user_id:
                raise ValueError(f"Session '{session_id}' does not belong to this user")
        else:
            session = self._session_store.create_session(agent_id, metadata=input, user_id=user_id)

        if input:
            session.merge_metadata(input)

        async with session.lock:
            session.append_user_message(message)
            session.truncate_history(self._session_store._max_history)

            agent_mem = agent.memory_config
            memory_block = await self._get_memory_block(
                agent_id, message, agent_mem, user_id=user_id
            )

            retriever_reg = snapshot.retriever_registry if snapshot else None
            system_prompt = await assemble_system_prompt(
                agent,
                snapshot.workspace,
                query=message,
                retriever_registry=retriever_reg,
                context_retrieval_config=snapshot.context_retrieval_config,
                memory_block=memory_block,
                chat_mode=True,
                user_instructions=user_instructions,
            )
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
                    input=session.metadata,
                    options=options,
                    handle=handle,
                    tool_executor=execute_tool,
                    message_history=messages,
                    caller_identity=user_id,
                    user_secrets=user_secrets,
                    user_config=user_config_values,
                )
            finally:
                self._execution_handles.pop(execution_id, None)

            result.duration_ms = int((time.monotonic() - start) * 1000)

            if result.raw_text:
                session.append_assistant_message(content=result.raw_text)

            # Persist conversation messages (async write-behind)
            self._persist_conversation_messages(session, message, result.raw_text)

            # Auto-extract memories from conversation (fire-and-forget, debounced)
            if (
                self._memory_manager is not None
                and agent_mem
                and agent_mem.auto_extract
                and self._llm_client is not None
            ):
                now = time.monotonic()
                debounce_key = f"{agent_id}:{user_id or ''}"
                last_extraction = self._extraction_cooldowns.get(debounce_key, 0.0)
                if now - last_extraction >= self._extraction_debounce:
                    self._extraction_cooldowns[debounce_key] = now
                    recent_messages = session.messages[-10:]
                    mm = self._memory_manager
                    _uid = user_id

                    async def _extract() -> None:
                        await mm.extract_memories(agent_id, recent_messages, user_id=_uid)
                        # Trigger compaction if threshold exceeded
                        await mm.compact_memories(agent_id, user_id=_uid)

                    task = asyncio.create_task(
                        _extract(),
                        name=f"memory-extract-{agent_id}-{user_id or 'global'}",
                    )
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

            return session.session_id, result

    # --- Programmatic session management ---

    def get_session(self, session_id: str) -> ChatSession | None:
        """Get a session by ID."""
        if self._session_store is None:
            return None
        return self._session_store.get_session(session_id)

    async def _get_or_restore_session(self, session_id: str) -> ChatSession | None:
        """Get session from cache, falling back to DB rehydration."""
        if self._session_store is None:
            return None

        # Fast path: cache hit
        session = self._session_store.get_session(session_id)
        if session is not None:
            return session

        # Deduplicate concurrent rehydrations
        if session_id in self._rehydration_tasks:
            try:
                return await self._rehydration_tasks[session_id]
            except asyncio.CancelledError:
                return None

        task = asyncio.create_task(self._rehydrate_session(session_id))
        self._rehydration_tasks[session_id] = task
        try:
            return await task
        except asyncio.CancelledError:
            return None
        finally:
            self._rehydration_tasks.pop(session_id, None)

    async def _rehydrate_session(self, session_id: str) -> ChatSession | None:
        """Load session from conversation persistence and restore to cache."""
        try:
            conv_record = await self._conversation_repo.get(session_id)
        except Exception:
            logger.warning(
                "Failed to load conversation %s for rehydration",
                session_id,
                exc_info=True,
            )
            return None

        if conv_record is None:
            return None

        if self._session_store is None:
            return None

        from datetime import UTC, datetime

        # Check TTL before rehydrating
        if conv_record.updated_at is not None:
            age_seconds = (datetime.now(UTC) - conv_record.updated_at).total_seconds()
            if age_seconds > self._session_store._ttl_seconds:
                logger.debug(
                    "Session %s expired (%.0fs old), skipping rehydration",
                    session_id,
                    age_seconds,
                )
                return None

        # Fetch the most recent messages by computing offset from message_count
        max_history = self._session_store._max_history
        msg_count = conv_record.message_count or 0
        offset = max(0, msg_count - max_history)

        try:
            db_messages = await self._conversation_repo.get_messages(
                session_id, limit=max_history, offset=offset
            )
        except Exception:
            logger.warning(
                "Failed to load messages for session %s",
                session_id,
                exc_info=True,
            )
            return None

        # Reconstruct message list: only user/assistant with non-empty content
        # (assistant turns that were tool-only have no persisted text content)
        messages: list[dict[str, Any]] = []
        for m in db_messages:
            if m.role == "user":
                messages.append({"role": "user", "content": m.content})
            elif m.role == "assistant" and m.content:
                messages.append({"role": "assistant", "content": m.content})

        # Drop dangling user message at tail (assistant response wasn't persisted)
        if messages and messages[-1]["role"] == "user":
            messages.pop()

        # Reconstruct _last_active from updated_at to preserve TTL
        now_mono = time.monotonic()
        if conv_record.updated_at is not None:
            age_seconds = (datetime.now(UTC) - conv_record.updated_at).total_seconds()
            last_active = now_mono - age_seconds
        else:
            last_active = now_mono

        now_ts = time.time()
        session = ChatSession(
            session_id=session_id,
            agent_id=conv_record.agent_id,
            user_id=conv_record.user_id,
            messages=messages,
            created_at=(conv_record.created_at.timestamp() if conv_record.created_at else now_ts),
            updated_at=(conv_record.updated_at.timestamp() if conv_record.updated_at else now_ts),
        )
        # Set _last_active for correct TTL behavior
        session._last_active = last_active

        self._session_store.restore_session(session)
        logger.info(
            "Rehydrated session %s from persistence (%d messages)",
            session_id,
            len(messages),
        )
        return session

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

    # --- Programmatic schedule management ---

    @property
    def scheduler(self) -> SchedulerEngine | None:
        """The scheduler engine, if active."""
        return self._scheduler

    async def list_schedules(self) -> list[dict[str, Any]]:
        """List all registered schedules."""
        if self._scheduler is None:
            return []
        return await self._scheduler.get_schedules()

    async def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        """Get details of a specific schedule."""
        if self._scheduler is None:
            return None
        return await self._scheduler.get_schedule(schedule_id)

    async def pause_schedule(self, schedule_id: str) -> bool:
        """Pause a schedule. Returns True if found and paused."""
        if self._scheduler is None:
            return False
        return await self._scheduler.pause(schedule_id)

    async def resume_schedule(self, schedule_id: str) -> bool:
        """Resume a paused schedule. Returns True if found and resumed."""
        if self._scheduler is None:
            return False
        return await self._scheduler.resume(schedule_id)

    async def trigger_schedule(self, schedule_id: str) -> str | None:
        """Manually trigger a schedule. Returns execution_id or None."""
        if self._scheduler is None:
            return None
        return await self._scheduler.trigger(schedule_id)

    async def update_schedule(
        self,
        schedule_id: str,
        cron_expr: str | None = None,
        message: str | None = None,
        timezone: str | None = None,
        enabled: bool | None = None,
        instructions: str | None = None,
    ) -> bool:
        """Update a schedule's configuration at runtime. Admin operation."""
        if self._scheduler is None:
            return False
        return await self._scheduler.update_schedule(
            schedule_id,
            cron_expr=cron_expr,
            message=message,
            timezone=timezone,
            enabled=enabled,
            instructions=instructions,
        )

    async def create_admin_schedule(
        self,
        agent_id: str,
        name: str,
        cron_expr: str,
        message: str,
        instructions: str | None = None,
        input_data: dict[str, Any] | None = None,
        timezone: str = "UTC",
        enabled: bool = True,
    ) -> str | None:
        """Create an admin-managed schedule. Returns schedule_id or None if scheduler inactive."""
        if self._scheduler is None:
            return None
        return await self._scheduler.create_admin_schedule(
            agent_id=agent_id,
            name=name,
            cron_expr=cron_expr,
            message=message,
            instructions=instructions,
            input_data=input_data,
            timezone=timezone,
            enabled=enabled,
        )

    async def delete_admin_schedule(self, schedule_id: str) -> bool:
        """Delete an admin-created schedule. Returns True if found and deleted."""
        if self._scheduler is None:
            return False
        return await self._scheduler.delete_admin_schedule(schedule_id)

    # --- Execution management ---

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a running execution. Returns True if cancelled.

        Checks in-memory handles first (sync or same-process async),
        then falls back to the queue backend (queued or cross-process).
        """
        # 1. Try in-memory handle (sync execution or same-process worker)
        handle = self._execution_handles.get(execution_id)
        if handle is not None:
            handle.cancel()
            return True

        # 2. Try queue backend (queued job or running on another worker)
        if not isinstance(self._queue, NullQueue):
            return await self._queue.request_cancel(execution_id)

        return False

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

    def set_input_schema(
        self,
        agent_id: str,
        schema: dict[str, Any] | type,
    ) -> None:
        """Set the input schema for an agent.

        Can be called with a JSON Schema dict or a Pydantic BaseModel class.
        Call before ``startup()`` — the schema is applied when the workspace loads.
        Code-registered schemas override AGENT.md frontmatter schemas.

        Usage::

            from pydantic import BaseModel

            class DealInput(BaseModel):
                deal_id: str
                amount: float

            gw.set_input_schema("underwriting", DealInput)
        """
        self._pending_input_schemas[agent_id] = schema

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
