"""Tool Registry and MCP Client Manager.

The Tool Registry provides centralized registration, lookup, and execution
of tools from multiple sources. The MCPClientManager handles connections to
MCP servers for dynamic tool discovery.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Literal

import yaml

from minirun.log import get_logger

log = get_logger("tools.registry")

# ── Retry / timeout defaults ────────────────────────────────────────────

MCP_CONNECT_RETRIES = 3
MCP_CONNECT_RETRY_DELAYS = (1.0, 2.0, 4.0)  # exponential backoff (seconds)
MCP_CONNECT_TIMEOUT = 10  # seconds
MCP_CALL_TOOL_TIMEOUT = 30  # seconds
MCP_MAX_CONCURRENT_CONNECTIONS = 5  # FR-010


@dataclass
class MCPClientConfig:
    """Configuration for a single MCP server connection."""

    name: str
    transport: Literal["stdio", "tcp"]
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    host: str | None = None
    port: int | None = None


@dataclass
class MCPServerTool:
    """A tool exposed by an MCP server."""

    server_name: str
    tool_name: str
    description: str | None = None
    input_schema: dict[str, object] | None = None


# Type alias for tool execution result
ToolResult = dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def register(self, name: str, execute_fn: Any, description: str = "") -> None:
        self._tools[name] = {
            "name": name,
            "execute": execute_fn,
            "description": description,
        }
        log.debug("Registered tool: %s", name)

    def get_tool(self, name: str) -> dict[str, Any] | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools.values())


class MCPClientManager:
    """Manages connections to MCP servers and tool discovery.

    Supports:
    - Retry with exponential backoff (3x: 1s, 2s, 4s) — **Step 1.2**
    - Concurrency limiting (≤5 simultaneous connects) — **FR-010**
    - Per-server serialization (lock per server) — **NFR-003**
    - Connect timeout (10s) and call_tool timeout (30s) — **Step 1.6**
    """

    def __init__(
        self,
        config_path: str | None = None,
    ) -> None:
        self._config_path = config_path or _default_mcp_config_path()
        self._servers: list[MCPClientConfig] = []
        self._sessions: dict[str, Any] = {}
        self._tools: list[MCPServerTool] = []
        self._initialized = False

        # Concurrency control (FR-010)
        self._connect_semaphore = asyncio.Semaphore(MCP_MAX_CONCURRENT_CONNECTIONS)
        self._server_locks: dict[str, asyncio.Lock] = {}

    def _get_server_lock(self, server_name: str) -> asyncio.Lock:
        """Return (or create) the per-server serialisation lock."""
        if server_name not in self._server_locks:
            self._server_locks[server_name] = asyncio.Lock()
        return self._server_locks[server_name]

    def load_config(self) -> None:
        path = self._config_path
        if not os.path.isfile(path):
            log.info("MCP config not found at %s — no MCP servers configured", path)
            self._servers = []
            return

        with open(path) as f:
            data = yaml.safe_load(f)

        if not data or "servers" not in data:
            self._servers = []
            return

        servers: list[MCPClientConfig] = []
        for name, cfg in data["servers"].items():
            transport = cfg.get("transport", "stdio")
            servers.append(
                MCPClientConfig(
                    name=name,
                    transport=transport,
                    command=cfg.get("command"),
                    args=cfg.get("args"),
                    env=cfg.get("env"),
                    host=cfg.get("host"),
                    port=cfg.get("port"),
                )
            )
        self._servers = servers
        log.info("Loaded %d MCP server configs", len(servers))

    @property
    def servers(self) -> list[MCPClientConfig]:
        """Configured MCP servers (read-only clone)."""
        return list(self._servers)

    @servers.setter
    def servers(self, value: list[MCPClientConfig]) -> None:
        self._servers = list(value)

    @property
    def sessions(self) -> dict[str, Any]:
        """Active MCP sessions (read-only clone)."""
        return dict(self._sessions)

    async def connect_all(self) -> None:
        """Connect to all configured MCP servers with concurrency limiting.

        Uses a semaphore to ensure at most *MCP_MAX_CONCURRENT_CONNECTIONS*
        servers are connecting simultaneously (FR-010).
        """
        self.load_config()

        tasks = [self._connect_with_semaphore(server) for server in self._servers]
        await asyncio.gather(*tasks)

        self._initialized = True
        log.info(
            "MCP: %d/%d servers connected",
            len(self._sessions),
            len(self._servers),
        )

    async def _connect_with_semaphore(self, config: MCPClientConfig) -> None:
        """Connect to a single MCP server, gated by the concurrency semaphore."""
        async with self._connect_semaphore:
            await self._connect_server_with_retry(config)

    async def _connect_server_with_retry(self, config: MCPClientConfig) -> None:
        """Connect to a single MCP server with exponential backoff retry.

        Retry logic (Step 1.2):
          - Up to *MCP_CONNECT_RETRIES* attempts
          - Delays: *MCP_CONNECT_RETRY_DELAYS* (1s, 2s, 4s)
          - Timeout per attempt: *MCP_CONNECT_TIMEOUT* (10s)
        """
        last_error: Exception | None = None
        attempts = MCP_CONNECT_RETRIES
        for attempt in range(1, attempts + 1):
            try:
                await asyncio.wait_for(
                    self._connect_server(config),
                    timeout=MCP_CONNECT_TIMEOUT,
                )
                return  # success
            except TimeoutError:
                last_error = TimeoutError(
                    f"MCP server {config.name}: connect timed out after "
                    f"{MCP_CONNECT_TIMEOUT}s"
                )
                log.warning(
                    "MCP connect timeout (attempt %d/%d): %s",
                    attempt,
                    attempts,
                    config.name,
                )
            except Exception as exc:
                last_error = exc
                log.warning(
                    "MCP connect failed (attempt %d/%d): %s — %s",
                    attempt,
                    attempts,
                    config.name,
                    exc,
                )

            if attempt < attempts:
                delay = MCP_CONNECT_RETRY_DELAYS[
                    min(attempt - 1, len(MCP_CONNECT_RETRY_DELAYS) - 1)
                ]
                log.info("Retrying MCP connect %s in %.1fs...", config.name, delay)
                await asyncio.sleep(delay)

        # All attempts exhausted
        log.error(
            "MCP connect failed after %d attempts: %s — %s",
            attempts,
            config.name,
            last_error,
        )

    async def _connect_server(self, config: MCPClientConfig) -> None:
        """Connect to a single MCP server (no retry — caller handles retries)."""
        try:
            from importlib import import_module

            _mcp = import_module("mcp")
            ClientSession = _mcp.ClientSession  # noqa: N806
            _mcp_client = import_module("mcp.client.sse")
            _mcp_stdio = import_module("mcp.client.stdio")
            sse_client = _mcp_client.sse_client
            StdioServerParameters = _mcp_stdio.StdioServerParameters  # noqa: N806
            stdio_client = _mcp_stdio.stdio_client
        except ImportError:
            log.error("MCP SDK not installed. Run: uv add mcp")
            return

        if config.transport == "stdio":
            if not config.command:
                log.error(
                    "MCP server %s: stdio transport requires a command",
                    config.name,
                )
                return

            server_params = StdioServerParameters(
                command=config.command,
                args=config.args or [],
                env=config.env,
            )
            read_stream, write_stream = await stdio_client(server_params).__aenter__()

        elif config.transport == "tcp":
            if not config.host or not config.port:
                log.error(
                    "MCP server %s: tcp transport requires host and port",
                    config.name,
                )
                return

            url = f"http://{config.host}:{config.port}/sse"
            read_stream, write_stream = await sse_client(url=url).__aenter__()

        else:
            log.error(
                "MCP server %s: unknown transport %s",
                config.name,
                config.transport,
            )
            return

        session = await ClientSession(read_stream, write_stream).__aenter__()
        await session.initialize()

        self._sessions[config.name] = {
            "session": session,
            "config": config,
            "read_stream": read_stream,
            "write_stream": write_stream,
        }
        log.info("Connected to MCP server: %s", config.name)

    async def list_tools(self) -> list[MCPServerTool]:
        if not self._initialized:
            await self.connect_all()

        tools: list[MCPServerTool] = []
        for name, session_data in self._sessions.items():
            session = session_data["session"]
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    tools.append(
                        MCPServerTool(
                            server_name=name,
                            tool_name=tool.name,
                            description=tool.description,
                            input_schema=(
                                tool.inputSchema
                                if hasattr(tool, "inputSchema")
                                else None
                            ),
                        )
                    )
            except Exception as exc:
                log.warning("Failed to list tools from %s: %s", name, exc)

        self._tools = tools
        log.info(
            "Discovered %d MCP tools from %d servers",
            len(tools),
            len(self._sessions),
        )
        return tools

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Call a tool on a specific MCP server.

        Tool calls to the *same* server are serialised via an ``asyncio.Lock``
        (NFR-003). Each call is subject to *MCP_CALL_TOOL_TIMEOUT* (30s).
        """
        session_data = self._sessions.get(server_name)
        if session_data is None:
            return {
                "success": False,
                "error": f"MCP server not connected: {server_name}",
            }

        session = session_data["session"]
        lock = self._get_server_lock(server_name)

        async with lock:
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments or {}),
                    timeout=MCP_CALL_TOOL_TIMEOUT,
                )
                return {
                    "success": True,
                    "content": result.content,
                    "isError": (
                        result.isError if hasattr(result, "isError") else False
                    ),
                }
            except TimeoutError:
                log.error(
                    "MCP tool call timed out after %ds: %s/%s",
                    MCP_CALL_TOOL_TIMEOUT,
                    server_name,
                    tool_name,
                )
                return {
                    "success": False,
                    "error": (
                        f"MCP call_tool timed out after "
                        f"{MCP_CALL_TOOL_TIMEOUT}s: "
                        f"{server_name}/{tool_name}"
                    ),
                }
            except Exception as exc:
                log.error(
                    "MCP tool call failed: %s/%s — %s",
                    server_name,
                    tool_name,
                    exc,
                )
                return {
                    "success": False,
                    "error": str(exc),
                }

    async def disconnect_all(self) -> None:
        for name, session_data in list(self._sessions.items()):
            try:
                session = session_data["session"]
                await session.__aexit__(None, None, None)
            except Exception as exc:
                log.warning("Error disconnecting MCP server %s: %s", name, exc)

        self._sessions.clear()
        self._tools = []
        self._initialized = False
        self._server_locks.clear()
        log.info("Disconnected from all MCP servers")


def _default_mcp_config_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config",
        "mcp.yaml",
    )


# Global registry instance
registry = ToolRegistry()
mcp_manager = MCPClientManager()
