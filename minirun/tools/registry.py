"""Tool Registry and MCP Client Manager.

The Tool Registry provides centralized registration, lookup, and execution
of tools from multiple sources. The MCPClientManager handles connections to
MCP servers for dynamic tool discovery.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import yaml

from minirun.log import get_logger

log = get_logger("tools.registry")


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

    def execute(self, name: str, params: dict[str, Any] | None = None) -> ToolResult:
        tool = self.get_tool(name)
        if tool is None:
            return {
                "success": False,
                "error": f"Unknown tool: {name}",
            }
        execute_fn = tool["execute"]
        try:
            result = execute_fn(name, params or {}, tool)
            return result
        except Exception as exc:
            log.error("Tool execution failed: %s — %s", name, exc)
            return {
                "success": False,
                "error": str(exc),
            }


class MCPClientManager:
    """Manages connections to MCP servers and tool discovery."""

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path or _default_mcp_config_path()
        self._servers: list[MCPClientConfig] = []
        self._sessions: dict[str, Any] = {}
        self._tools: list[MCPServerTool] = []
        self._initialized = False

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
        self.load_config()

        for server in self._servers:
            try:
                await self._connect_server(server)
            except Exception as exc:
                log.warning(
                    "Failed to connect MCP server %s: %s",
                    server.name,
                    exc,
                )

        self._initialized = True
        log.info(
            "MCP: %d/%d servers connected",
            len(self._sessions),
            len(self._servers),
        )

    async def _connect_server(self, config: MCPClientConfig) -> None:
        try:
            from importlib import import_module

            _mcp = import_module("mcp")
            ClientSession = _mcp.ClientSession
            _mcp_client = import_module("mcp.client.sse")
            _mcp_stdio = import_module("mcp.client.stdio")
            sse_client = _mcp_client.sse_client
            StdioServerParameters = _mcp_stdio.StdioServerParameters
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
        self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> ToolResult:
        session_data = self._sessions.get(server_name)
        if session_data is None:
            return {
                "success": False,
                "error": f"MCP server not connected: {server_name}",
            }

        session = session_data["session"]
        try:
            result = await session.call_tool(tool_name, arguments or {})
            return {
                "success": True,
                "content": result.content,
                "isError": result.isError if hasattr(result, "isError") else False,
            }
        except Exception as exc:
            log.error("MCP tool call failed: %s/%s — %s", server_name, tool_name, exc)
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
