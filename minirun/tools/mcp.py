"""MCP (Model Context Protocol) Client — re-exports from registry.

This module provides the MCP client interface for connecting to MCP servers
and discovering/invoking tools. The actual implementation lives in
minirun.tools.registry to avoid circular imports.
"""

from __future__ import annotations

from minirun.tools.registry import (
    MCPClientConfig,
    MCPClientManager,
    MCPServerTool,
    mcp_manager,
)

__all__ = [
    "MCPClientConfig",
    "MCPClientManager",
    "MCPServerTool",
    "mcp_manager",
]
