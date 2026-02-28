"""MCP connection manager — manages client connections to MCP servers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from agent_gateway.exceptions import McpConnectionError, McpToolExecutionError
from agent_gateway.mcp.auth import McpHttpAuth, McpTokenProvider, build_auth_from_credentials
from agent_gateway.mcp.domain import McpToolInfo
from agent_gateway.persistence.domain import McpServerConfig
from agent_gateway.secrets import decrypt_json_blob

logger = logging.getLogger(__name__)


@dataclass
class McpConnection:
    """A live connection to a single MCP server."""

    config: McpServerConfig
    session: ClientSession
    tools: list[McpToolInfo] = field(default_factory=list)
    token_provider: Any = None  # McpTokenProvider | None, kept for reconnection
    # Lifecycle handles
    _shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)
    _background_task: asyncio.Task[None] | None = None


class McpConnectionManager:
    """Manages MCP client connections to configured servers.

    Owned by Gateway (stored as Gateway._mcp_manager). Passed to
    ExecutionEngine and injected into ToolContext so the tool runner
    can call MCP tools without singletons.
    """

    def __init__(
        self,
        connection_timeout_ms: int = 10_000,
        tool_call_timeout_ms: int = 30_000,
    ) -> None:
        self._connections: dict[str, McpConnection] = {}  # keyed by server name
        self._connection_timeout_s = connection_timeout_ms / 1000.0
        self._tool_call_timeout_s = tool_call_timeout_ms / 1000.0

    async def connect_all(
        self,
        configs: list[McpServerConfig],
        token_providers: dict[str, McpTokenProvider] | None = None,
    ) -> None:
        """Connect to all enabled MCP servers. Called during gateway startup.

        Failures are logged and skipped -- never blocks startup.
        """
        providers = token_providers or {}
        for config in configs:
            if not config.enabled:
                continue
            try:
                await self._connect_one(config, token_provider=providers.get(config.name))
                logger.info(
                    "Connected to MCP server '%s' (%s), discovered %d tools",
                    config.name,
                    config.transport,
                    len(self._connections[config.name].tools),
                )
            except Exception:
                logger.error(
                    "Failed to connect to MCP server '%s'",
                    config.name,
                    exc_info=True,
                )

    async def _connect_one(
        self,
        config: McpServerConfig,
        token_provider: McpTokenProvider | None = None,
    ) -> None:
        """Establish connection to a single MCP server.

        Spawns a background task that enters the transport and session
        context managers and blocks on a shutdown event. The session
        is made available immediately via a ready_event.
        """
        # Decrypt credentials and env
        try:
            credentials = decrypt_json_blob(config.encrypted_credentials)
        except Exception:
            logger.warning(
                "Failed to decrypt credentials for MCP server '%s', using empty credentials",
                config.name,
            )
            credentials = {}
        try:
            env_vars = decrypt_json_blob(config.encrypted_env)
        except Exception:
            logger.warning(
                "Failed to decrypt env for MCP server '%s', using empty env",
                config.name,
            )
            env_vars = {}

        shutdown_event = asyncio.Event()
        ready_event = asyncio.Event()
        session_holder: list[ClientSession] = []  # mutable container for the session
        error_holder: list[Exception] = []

        async def _run_connection() -> None:
            """Background task: enter transport CM + session CM, block until shutdown."""
            try:
                if config.transport == "stdio":
                    if config.command is None:
                        raise ValueError(
                            f"MCP server '{config.name}': stdio transport requires 'command'"
                        )
                    # Merge decrypted env vars into subprocess environment
                    merged_env = dict(env_vars) if env_vars else None
                    server_params = StdioServerParameters(
                        command=config.command,
                        args=config.args or [],
                        env=merged_env,
                    )
                    async with (
                        stdio_client(server_params) as (read, write),
                        ClientSession(read, write) as session,
                    ):
                        await session.initialize()
                        session_holder.append(session)
                        ready_event.set()
                        # Block here until shutdown is requested
                        await shutdown_event.wait()

                elif config.transport == "streamable_http":
                    if config.url is None:
                        raise ValueError(
                            f"MCP server '{config.name}': streamable_http transport requires 'url'"
                        )

                    # Determine auth: user-provided token_provider takes precedence,
                    # otherwise build from credentials dict.
                    auth: httpx.Auth | None = None
                    if token_provider is not None:
                        auth = McpHttpAuth(token_provider)
                    elif credentials:
                        auth = build_auth_from_credentials(credentials, server_name=config.name)

                    # Build static headers: legacy plaintext fallback, then encrypted
                    headers = dict(config.headers or {})
                    try:
                        encrypted_hdrs = decrypt_json_blob(config.encrypted_headers)
                    except Exception:
                        logger.warning(
                            "Failed to decrypt headers for MCP server '%s', skipping",
                            config.name,
                        )
                        encrypted_hdrs = {}
                    if encrypted_hdrs:
                        headers.update(encrypted_hdrs)
                    if credentials:
                        # Merge encrypted headers from credentials
                        if "headers" in credentials and isinstance(credentials["headers"], dict):
                            headers.update(credentials["headers"])
                        # Legacy path: inject static Authorization header from credentials
                        if auth is None:
                            if "bearer_token" in credentials:
                                headers["Authorization"] = f"Bearer {credentials['bearer_token']}"
                            if "api_key" in credentials and "api_key_header" in credentials:
                                headers[credentials["api_key_header"]] = credentials["api_key"]
                        # Pass-through: any remaining keys that look like HTTP headers
                        # (contain a hyphen, e.g. "X-Goog-Api-Key") are treated as headers.
                        _reserved = {
                            "headers",
                            "bearer_token",
                            "api_key",
                            "api_key_header",
                            "auth_type",
                            "token_url",
                            "client_id",
                            "client_secret",
                            "scopes",
                            "service_account_json",
                        }
                        for key, value in credentials.items():
                            if key not in _reserved and isinstance(value, str):
                                headers[key] = value

                    # Construct httpx.AsyncClient with auth and headers.
                    # Note: headers are set on the AsyncClient (not passed to
                    # streamable_http_client) because the SDK API only accepts
                    # http_client=. The AsyncClient lifecycle must be inside
                    # _run_connection() so it stays open for the MCP session.
                    http_client = httpx.AsyncClient(
                        auth=auth,
                        headers=headers,
                    )
                    async with (
                        http_client,
                        streamable_http_client(config.url, http_client=http_client) as (
                            read,
                            write,
                            _get_session_id,
                        ),
                        ClientSession(read, write) as session,
                    ):
                        await session.initialize()
                        session_holder.append(session)
                        ready_event.set()
                        await shutdown_event.wait()

                else:
                    raise ValueError(
                        f"MCP server '{config.name}': unsupported transport '{config.transport}'"
                    )
            except Exception as exc:
                error_holder.append(exc)
                ready_event.set()  # unblock the caller even on failure

        # Spawn background task
        task = asyncio.create_task(_run_connection(), name=f"mcp-{config.name}")

        # Wait for the session to be ready, with timeout
        try:
            await asyncio.wait_for(ready_event.wait(), timeout=self._connection_timeout_s)
        except TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise McpConnectionError(
                f"MCP server '{config.name}' connection timed out "
                f"after {self._connection_timeout_s}s",
                server_name=config.name,
            ) from None

        if error_holder:
            # Task failed during setup -- cancel it and re-raise
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise error_holder[0]

        if not session_holder:
            task.cancel()
            raise RuntimeError(f"MCP server '{config.name}': session not established")

        session = session_holder[0]

        # Discover tools
        tools_result = await session.list_tools()
        discovered: list[McpToolInfo] = []
        for t in tools_result.tools:
            if not hasattr(t, "inputSchema"):
                logger.debug(
                    "MCP tool '%s' on server '%s' has no inputSchema, using empty schema",
                    t.name,
                    config.name,
                )
            discovered.append(
                McpToolInfo(
                    server_name=config.name,
                    name=t.name,
                    description=t.description or "",
                    input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
                )
            )

        conn = McpConnection(
            config=config,
            session=session,
            tools=discovered,
            token_provider=token_provider,
            _shutdown_event=shutdown_event,
            _background_task=task,
        )
        self._connections[config.name] = conn

    async def test_connection(
        self,
        config: McpServerConfig,
        token_provider: McpTokenProvider | None = None,
    ) -> dict[str, Any]:
        """Test connectivity to an MCP server without storing the connection.

        Performs an ephemeral connect -> list_tools -> disconnect cycle.
        Returns {"success": True, "tools": [...], "tool_count": N}.
        Raises McpConnectionError on failure.
        """
        # Decrypt credentials and env
        try:
            credentials = decrypt_json_blob(config.encrypted_credentials)
        except Exception:
            logger.warning(
                "Failed to decrypt credentials for MCP server '%s', using empty credentials",
                config.name,
            )
            credentials = {}
        try:
            env_vars = decrypt_json_blob(config.encrypted_env)
        except Exception:
            logger.warning(
                "Failed to decrypt env for MCP server '%s', using empty env",
                config.name,
            )
            env_vars = {}

        shutdown_event = asyncio.Event()
        ready_event = asyncio.Event()
        session_holder: list[ClientSession] = []
        error_holder: list[Exception] = []

        async def _run_connection() -> None:
            try:
                if config.transport == "stdio":
                    if config.command is None:
                        raise ValueError(
                            f"MCP server '{config.name}': stdio transport requires 'command'"
                        )
                    merged_env = dict(env_vars) if env_vars else None
                    server_params = StdioServerParameters(
                        command=config.command,
                        args=config.args or [],
                        env=merged_env,
                    )
                    async with (
                        stdio_client(server_params) as (read, write),
                        ClientSession(read, write) as session,
                    ):
                        await session.initialize()
                        session_holder.append(session)
                        ready_event.set()
                        await shutdown_event.wait()

                elif config.transport == "streamable_http":
                    if config.url is None:
                        raise ValueError(
                            f"MCP server '{config.name}': streamable_http transport requires 'url'"
                        )
                    auth: httpx.Auth | None = None
                    if token_provider is not None:
                        auth = McpHttpAuth(token_provider)
                    elif credentials:
                        auth = build_auth_from_credentials(credentials, server_name=config.name)
                    headers = dict(config.headers or {})
                    try:
                        encrypted_hdrs = decrypt_json_blob(config.encrypted_headers)
                    except Exception:
                        logger.warning(
                            "Failed to decrypt headers for MCP server '%s', skipping",
                            config.name,
                        )
                        encrypted_hdrs = {}
                    if encrypted_hdrs:
                        headers.update(encrypted_hdrs)
                    if auth is None and credentials:
                        if "bearer_token" in credentials:
                            headers["Authorization"] = f"Bearer {credentials['bearer_token']}"
                        if "api_key" in credentials and "api_key_header" in credentials:
                            headers[credentials["api_key_header"]] = credentials["api_key"]
                    http_client = httpx.AsyncClient(auth=auth, headers=headers)
                    async with (
                        http_client,
                        streamable_http_client(config.url, http_client=http_client) as (
                            read,
                            write,
                            _get_session_id,
                        ),
                        ClientSession(read, write) as session,
                    ):
                        await session.initialize()
                        session_holder.append(session)
                        ready_event.set()
                        await shutdown_event.wait()
                else:
                    raise ValueError(
                        f"MCP server '{config.name}': unsupported transport '{config.transport}'"
                    )
            except Exception as exc:
                error_holder.append(exc)
                ready_event.set()

        task = asyncio.create_task(_run_connection(), name=f"mcp-test-{config.name}")

        try:
            try:
                await asyncio.wait_for(ready_event.wait(), timeout=self._connection_timeout_s)
            except TimeoutError:
                raise McpConnectionError(
                    f"MCP server '{config.name}' test connection timed out "
                    f"after {self._connection_timeout_s}s",
                    server_name=config.name,
                ) from None

            if error_holder:
                raise error_holder[0]

            if not session_holder:
                raise RuntimeError(f"MCP server '{config.name}': session not established")

            session = session_holder[0]
            tools_result = await asyncio.wait_for(
                session.list_tools(), timeout=self._tool_call_timeout_s
            )
            tools: list[dict[str, Any]] = []
            for t in tools_result.tools:
                tools.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                    }
                )

            return {
                "success": True,
                "tools": tools,
                "tool_count": len(tools),
            }
        finally:
            shutdown_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(task, timeout=5.0)

    async def disconnect_all(self) -> None:
        """Gracefully close all connections. Called during gateway shutdown."""
        for name, conn in self._connections.items():
            try:
                conn._shutdown_event.set()  # signal the background task to exit
                if conn._background_task is not None:
                    await asyncio.wait_for(conn._background_task, timeout=5.0)
            except Exception:
                logger.warning("Error disconnecting MCP server '%s'", name, exc_info=True)
        self._connections.clear()

    async def disconnect_one(self, name: str) -> None:
        """Disconnect a single server."""
        conn = self._connections.pop(name, None)
        if conn is None:
            return
        conn._shutdown_event.set()
        if conn._background_task is not None:
            try:
                await asyncio.wait_for(conn._background_task, timeout=5.0)
            except Exception:
                logger.warning("Error disconnecting MCP server '%s'", name, exc_info=True)

    async def refresh_server(
        self,
        name: str,
        config: McpServerConfig,
        token_provider: McpTokenProvider | None = None,
    ) -> None:
        """Reconnect a single server (after config change)."""
        await self.disconnect_one(name)
        await self._connect_one(config, token_provider=token_provider)

    def get_tools(self, server_name: str) -> list[McpToolInfo]:
        """Get discovered tools for a server. Returns empty list if not connected."""
        conn = self._connections.get(server_name)
        if conn is None:
            return []
        return list(conn.tools)

    def get_all_tools(self) -> dict[str, list[McpToolInfo]]:
        """Get all discovered tools grouped by server name."""
        return {name: list(c.tools) for name, c in self._connections.items()}

    def is_connected(self, server_name: str) -> bool:
        """Check if a server has an active connection."""
        conn = self._connections.get(server_name)
        if conn is None:
            return False
        task = conn._background_task
        return task is not None and not task.done()

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Proxy a tool call to the appropriate MCP server."""
        conn = self._connections.get(server_name)
        if conn is None:
            raise McpToolExecutionError(
                f"MCP server '{server_name}' is not connected",
                server_name=server_name,
                tool_name=tool_name,
            )

        # Auto-reconnect if background task has died
        if conn._background_task is None or conn._background_task.done():
            logger.warning("MCP server '%s' connection lost, attempting reconnect…", server_name)
            try:
                await self._connect_one(conn.config, conn.token_provider)
                conn = self._connections.get(server_name)
                if conn is None or conn._background_task is None or conn._background_task.done():
                    raise McpToolExecutionError(
                        f"MCP server '{server_name}' reconnection failed",
                        server_name=server_name,
                        tool_name=tool_name,
                    )
                logger.info("MCP server '%s' reconnected successfully", server_name)
            except McpToolExecutionError:
                raise
            except Exception as exc:
                raise McpToolExecutionError(
                    f"MCP server '{server_name}' reconnection failed: {exc}",
                    server_name=server_name,
                    tool_name=tool_name,
                ) from exc

        try:
            result = await asyncio.wait_for(
                conn.session.call_tool(tool_name, arguments=arguments),
                timeout=self._tool_call_timeout_s,
            )
        except TimeoutError:
            raise McpToolExecutionError(
                f"MCP tool '{tool_name}' on server '{server_name}' timed out "
                f"after {self._tool_call_timeout_s}s",
                server_name=server_name,
                tool_name=tool_name,
            ) from None
        return _format_mcp_result(result)


def _format_mcp_result(result: Any) -> str:
    """Format MCP CallToolResult content into a string for the LLM."""
    parts: list[str] = []
    for item in result.content:
        if hasattr(item, "text"):
            parts.append(item.text)
        elif hasattr(item, "data"):
            mime = getattr(item, "mimeType", None) or "unknown"
            parts.append(f"[binary content: {mime}]")
        else:
            parts.append(str(item))
    return "\n".join(parts)


def compute_server_to_agents(
    workspace: Any,
) -> dict[str, list[str]]:
    """Scan all agents' mcp_servers lists and build a reverse mapping.

    Returns: {server_name: [agent_id, ...]}
    """
    result: dict[str, list[str]] = {}
    for agent in workspace.agents.values():
        for server_name in agent.mcp_servers:
            result.setdefault(server_name, []).append(agent.id)
    return result
