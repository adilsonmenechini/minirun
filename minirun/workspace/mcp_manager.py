"""MCP Profile Manager — manages MCP connections scoped to a profile."""

from __future__ import annotations

import os
from typing import Any

from minirun.log import get_logger
from minirun.tools.registry import MCPClientConfig, MCPClientManager, MCPServerTool
from minirun.workspace.models import MCPServerConfig, WorkspaceProfile

log = get_logger("workspace.mcp_manager")


class MCPProfileManager:
    """Manages MCP server connections scoped to a specific profile."""

    def __init__(self, profile: WorkspaceProfile) -> None:
        self.profile = profile
        self._mcp_manager = MCPClientManager()
        self._initialized = False

    def _substitute_env_vars(self, value: str) -> str:
        """Substitute environment variables in the form ${VAR_NAME}."""
        import re

        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", replace, value)

    def _convert_server_config(self, server: MCPServerConfig) -> MCPClientConfig:
        """Convert MCPServerConfig to MCPClientConfig with env var sub."""
        env = {}
        if server.env:
            for key, value in server.env.items():
                env[key] = self._substitute_env_vars(value)

        command = self._substitute_env_vars(server.command) if server.command else None
        args_list = (
            [self._substitute_env_vars(arg) for arg in server.args]
            if server.args
            else None
        )
        host = self._substitute_env_vars(server.host) if server.host else None
        return MCPClientConfig(
            name=server.name,
            transport=server.transport,
            command=command,
            args=args_list,
            env=env if env else None,
            host=host,
            port=server.port,
        )

    async def connect_all(self) -> None:
        self._mcp_manager.servers = [
            self._convert_server_config(server) for server in self.profile.mcp_servers
        ]
        log.info(
            "Configured %d MCP servers for profile %s",
            len(self._mcp_manager.servers),
            self.profile.name,
        )

        await self._mcp_manager.connect_all()

        self._initialized = True
        log.info(
            "MCPProfileManager: %d/%d servers connected for profile %s",
            len(self._mcp_manager.sessions),
            len(self._mcp_manager.servers),
            self.profile.name,
        )

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers. Idempotent."""
        await self._mcp_manager.disconnect_all()
        self._initialized = False
        log.info("Disconnected from all MCP servers for profile %s", self.profile.name)

    async def list_tools(self) -> list[MCPServerTool]:
        """Return tools from all connected profile MCP servers."""
        if not self._initialized:
            await self.connect_all()

        return await self._mcp_manager.list_tools()

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a tool on a specific profile MCP server."""
        if not self._initialized:
            await self.connect_all()

        return await self._mcp_manager.call_tool(
            server_name, tool_name, arguments or {}
        )

    @property
    def mcp_manager(self) -> MCPClientManager:
        """Access the underlying MCPClientManager."""
        return self._mcp_manager
