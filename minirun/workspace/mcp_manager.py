"""MCP Profile Manager — manages MCP connections scoped to a profile.

Phase 1 responsibilities (spec.md):
- Load MCP server config from profile frontmatter (Step 1.1)
- Validate ``${VAR_NAME}`` env vars before connecting (Step 1.8)
- Validate ``allowed_tools`` against discovered MCP tools (Step 1.7)
- Log all MCP events at INFO level + EventJournal (Step 1.9)
"""

from __future__ import annotations

import os
import re
from typing import Any

from minirun.log import get_logger
from minirun.runtime.events import safe_emit
from minirun.tools.registry import MCPClientConfig, MCPClientManager, MCPServerTool
from minirun.workspace.models import MCPServerConfig, WorkspaceProfile

log = get_logger("workspace.mcp_manager")


class MCPProfileManager:
    """Manages MCP server connections scoped to a specific profile.

    Args:
        profile: The workspace profile whose ``mcp_servers`` will be managed.
        mcp_manager: Optional pre-configured :class:`MCPClientManager`.
            If omitted a new instance is created, which provides retry,
            concurrency limiting, timeouts, and per-server serialisation
            (Steps 1.2, 1.4, 1.5, 1.6).
    """

    def __init__(
        self,
        profile: WorkspaceProfile,
        mcp_manager: MCPClientManager | None = None,
    ) -> None:
        self.profile = profile
        self._mcp_manager = mcp_manager or MCPClientManager()
        self._initialized = False

    # ── Env var substitution & validation (Step 1.8) ────────────────────

    _ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

    def _substitute_env_vars(self, value: str) -> str:
        """Substitute environment variables in the form ``${VAR_NAME}``.

        Unresolved variables are left as-is (not replaced).
        """

        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))

        return self._ENV_VAR_PATTERN.sub(replace, value)

    def validate_env_vars(self) -> list[str]:
        """Check all MCP server env values for unresolved ``${VAR_NAME}``.

        Returns a list of error messages for every missing variable.
        Raises ``ValueError`` with a combined message if any are missing
        (NFR-006).  Callers MUST invoke this before ``connect_all()``.
        """
        missing: list[str] = []
        for server in self.profile.mcp_servers:
            # Check command / args
            for field, label in [
                (server.command, "command"),
                (server.host, "host"),
            ]:
                if field:
                    unresolved = self._ENV_VAR_PATTERN.findall(field)
                    for var in unresolved:
                        if var not in os.environ:
                            missing.append(
                                f"Server '{server.name}': env var "
                                f"'${{{var}}}' not set ({label})"
                            )

            if server.args:
                for arg in server.args:
                    unresolved = self._ENV_VAR_PATTERN.findall(arg)
                    for var in unresolved:
                        if var not in os.environ:
                            missing.append(
                                f"Server '{server.name}': env var "
                                f"'${{{var}}}' not set (args)"
                            )

            # Check env dict values
            if server.env:
                for key, value in server.env.items():
                    unresolved = self._ENV_VAR_PATTERN.findall(value)
                    for var in unresolved:
                        if var not in os.environ:
                            missing.append(
                                f"Server '{server.name}': env var "
                                f"'${{{var}}}' not set (env.{key})"
                            )

        if missing:
            raise ValueError(
                "Missing required environment variables (NFR-006):\n"
                + "\n".join(f"  - {m}" for m in missing)
            )
        return missing

    # ── Allowed tools validation (Step 1.7) ─────────────────────────────

    def validate_allowed_tools(
        self,
        discovered_tools: list[MCPServerTool],
    ) -> dict[str, list[str]]:
        """Validate profile ``allowed_tools`` against discovered MCP tools.

        Logs warnings for ``allowed_tools`` entries that reference unknown
        MCP tools and for discovered tools not in ``allowed_tools``.

        Args:
            discovered_tools: Tools returned by :meth:`list_tools`.

        Returns:
            A dict with two keys:
              - ``"unrecognised"``: allowed_tools with no matching MCP tool
              - ``"undiscovered"``: MCP tools not in allowed_tools
        """
        allowed = set(self.profile.allowed_tools)
        discovered = {f"{t.server_name}.{t.tool_name}" for t in discovered_tools}

        unrecognised = sorted(allowed - discovered)
        undiscovered = sorted(discovered - allowed)

        if unrecognised:
            log.warning(
                "Profile '%s': allowed_tools not found among MCP tools: %s",
                self.profile.name,
                ", ".join(unrecognised),
            )
        if undiscovered:
            log.debug(
                "Profile '%s': MCP tools not in allowed_tools: %s",
                self.profile.name,
                ", ".join(undiscovered),
            )

        return {
            "unrecognised": unrecognised,
            "undiscovered": undiscovered,
        }

    # ── Lifecycle ───────────────────────────────────────────────────────

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
        """Connect to all MCP servers for this profile.

        Validates env vars first (NFR-006), then delegates to
        :class:`MCPClientManager` which provides retry, concurrency
        limiting, and timeouts.
        """
        # Step 1.8: Validate environment variables before connecting
        self.validate_env_vars()

        self._mcp_manager.servers = [
            self._convert_server_config(server) for server in self.profile.mcp_servers
        ]
        log.info(
            "Configured %d MCP servers for profile %s",
            len(self._mcp_manager.servers),
            self.profile.name,
        )

        for server in self.profile.mcp_servers:
            log.info(
                "MCP event: connecting to server '%s' (transport=%s)",
                server.name,
                server.transport,
            )
            safe_emit(
                session_id="system",
                event_type="mcp_connect",
                payload={
                    "profile": self.profile.name,
                    "server": server.name,
                    "transport": server.transport,
                },
            )

        await self._mcp_manager.connect_all()

        # Step 1.9: Log connection results
        connected = len(self._mcp_manager.sessions)
        total = len(self._mcp_manager.servers)
        self._initialized = True

        if connected < total:
            log.warning(
                "MCP event: profile '%s' — %d/%d servers connected (degraded mode)",
                self.profile.name,
                connected,
                total,
            )
            for server_cfg in self.profile.mcp_servers:
                if server_cfg.name not in self._mcp_manager.sessions:
                    safe_emit(
                        session_id="system",
                        event_type="mcp_connect_error",
                        payload={
                            "profile": self.profile.name,
                            "server": server_cfg.name,
                            "error": "Connection failed after retries",
                        },
                    )
        else:
            log.info(
                "MCP event: profile '%s' — all %d servers connected",
                self.profile.name,
                total,
            )

        safe_emit(
            session_id="system",
            event_type="mcp_connect_complete",
            payload={
                "profile": self.profile.name,
                "connected": connected,
                "total": total,
            },
        )

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers. Idempotent."""
        await self._mcp_manager.disconnect_all()
        self._initialized = False
        log.info(
            "MCP event: disconnected all servers for profile '%s'",
            self.profile.name,
        )
        safe_emit(
            session_id="system",
            event_type="mcp_disconnect",
            payload={"profile": self.profile.name},
        )

    async def list_tools(self) -> list[MCPServerTool]:
        """Return tools from all connected profile MCP servers.

        Automatically validates ``allowed_tools`` against discovered tools
        after discovery (FR-008 / Step 1.7).
        """
        if not self._initialized:
            await self.connect_all()

        discovered = await self._mcp_manager.list_tools()

        # Step 1.7: validate allowed_tools at discovery time
        self.validate_allowed_tools(discovered)

        return discovered

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a tool on a specific profile MCP server.

        The underlying :class:`MCPClientManager` handles per-server
        serialisation (NFR-003) and the 30s ``call_tool`` timeout.
        """
        if not self._initialized:
            await self.connect_all()

        log.info(
            "MCP event: calling tool '%s/%s' on profile '%s'",
            server_name,
            tool_name,
            self.profile.name,
        )
        safe_emit(
            session_id="system",
            event_type="mcp_tool_call",
            payload={
                "profile": self.profile.name,
                "server": server_name,
                "tool": tool_name,
            },
        )

        result = await self._mcp_manager.call_tool(
            server_name,
            tool_name,
            arguments or {},
        )

        safe_emit(
            session_id="system",
            event_type="mcp_tool_result",
            payload={
                "profile": self.profile.name,
                "server": server_name,
                "tool": tool_name,
                "success": result.get("success", False),
            },
        )
        return result

    @property
    def mcp_manager(self) -> MCPClientManager:
        """Access the underlying MCPClientManager."""
        return self._mcp_manager

    @property
    def connected_count(self) -> int:
        """Number of currently connected MCP servers."""
        return len(self._mcp_manager.sessions)

    @property
    def configured_count(self) -> int:
        """Number of configured MCP servers for this profile."""
        return len(self._mcp_manager.servers)
