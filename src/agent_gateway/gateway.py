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

if TYPE_CHECKING:
    from agent_gateway.scheduler.engine import SchedulerEngine

from agent_gateway.auth.protocols import AuthProvider
from agent_gateway.chat.session import ChatSession, SessionStore
from agent_gateway.config import GatewayConfig, NotificationsConfig, PersistenceConfig
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
)
from agent_gateway.notifications.protocols import NotificationBackend
from agent_gateway.persistence.backend import PersistenceBackend
from agent_gateway.persistence.null import (
    NullAuditRepository,
    NullExecutionRepository,
    NullScheduleRepository,
)
from agent_gateway.persistence.protocols import (
    AuditRepository,
    ExecutionRepository,
    ScheduleRepository,
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
        auth: bool | Callable[..., Any] | AuthProvider = True,
        reload: bool = False,
        **fastapi_kwargs: Any,
    ) -> None:
        self._workspace_path = str(workspace)
        self._auth_setting = auth
        self._reload_enabled = reload
        self._pending_tools: list[CodeTool] = []
        self._pending_input_schemas: dict[str, dict[str, Any] | type] = {}
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

        # 7. Build LLM client and execution engine
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

        # 7.5. Apply code-registered input schemas (overrides frontmatter)
        self._apply_pending_input_schemas(workspace)

        # 8. Atomic snapshot
        self._snapshot = WorkspaceSnapshot(
            workspace=workspace,
            tool_registry=tool_registry,
            engine=engine,
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

                self._scheduler = SchedulerEngine(
                    config=self._config.scheduler,
                    schedule_repo=self._schedule_repo,
                    execution_repo=self._execution_repo,
                    queue=self._queue,
                    invoke_fn=self.invoke,
                    track_task=_track_task,
                    timezone=self._config.timezone,
                )
                await self._scheduler.start(
                    schedules=workspace.schedules,
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
            )
            await self._notification_worker.start()

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
        Agents reference endpoints by name in CONFIG.md.

        Args:
            url: Webhook URL to POST to.
            name: Endpoint name (referenced in agent CONFIG.md).
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
            if providers:
                self._auth_provider = CompositeProvider(providers)
                return self._auth_provider

        return None

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

    def _register_routes(self) -> None:
        """Mount all /v1/ API routes."""
        from agent_gateway.api.routes.base import GatewayAPIRoute
        from agent_gateway.api.routes.chat import router as chat_router
        from agent_gateway.api.routes.executions import router as executions_router
        from agent_gateway.api.routes.health import router as health_router
        from agent_gateway.api.routes.introspection import router as introspection_router
        from agent_gateway.api.routes.invoke import router as invoke_router
        from agent_gateway.api.routes.schedules import router as schedules_router

        v1 = APIRouter(prefix="/v1", route_class=GatewayAPIRoute)
        v1.include_router(health_router)
        v1.include_router(invoke_router)
        v1.include_router(chat_router)
        v1.include_router(executions_router)
        v1.include_router(introspection_router)
        v1.include_router(schedules_router)

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

            # Re-apply code-registered input schemas
            self._apply_pending_input_schemas(new_workspace)

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
        """
        if not self._notification_engine.has_backends or not config:
            return

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
            task = asyncio.create_task(self._notification_engine.notify(event, config))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def invoke(
        self,
        agent_id: str,
        message: str,
        input: dict[str, Any] | None = None,
        options: ExecutionOptions | None = None,
    ) -> ExecutionResult:
        """Invoke an agent programmatically (bypasses HTTP).

        Args:
            agent_id: The agent to invoke.
            message: The user message.
            input: Optional input dict.
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

        execution_id = str(uuid.uuid4())
        handle = ExecutionHandle(execution_id=execution_id)
        self._execution_handles[execution_id] = handle

        try:
            result = await snapshot.engine.execute(
                agent=agent,
                message=message,
                workspace=snapshot.workspace,
                input=input,
                options=options,
                handle=handle,
                tool_executor=execute_tool,
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
    ) -> tuple[str, ExecutionResult]:
        """Send a chat message programmatically (bypasses HTTP).

        Args:
            agent_id: The agent to chat with.
            message: The user message.
            session_id: Optional existing session ID. Creates new session if None.
            input: Optional input dict.
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
            session = self._session_store.create_session(agent_id, metadata=input)

        if input:
            session.merge_metadata(input)

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
                    input=session.metadata,
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
