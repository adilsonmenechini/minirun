from __future__ import annotations

from typing import Any

from minirun.tools.filesystem import FilesystemTool
from minirun.tools.http import HTTPTool
from minirun.tools.registry import (
    MCPClientConfig,
    MCPClientManager,
    MCPServerTool,
    ToolRegistry,
    mcp_manager,
    registry,
)
from minirun.tools.shell import ShellTool

_http_tool = HTTPTool()


def _execute_http_get(
    name: str, params: dict[str, Any], tool: dict[str, Any]
) -> dict[str, Any]:
    return _http_tool.execute({**params, "method": "GET"})


def _execute_http_post(
    name: str, params: dict[str, Any], tool: dict[str, Any]
) -> dict[str, Any]:
    return _http_tool.execute({**params, "method": "POST"})


registry.register(
    name="http.get",
    execute_fn=_execute_http_get,
    description="Make HTTP GET requests to REST APIs",
)
registry.register(
    name="http.post",
    execute_fn=_execute_http_post,
    description="Make HTTP POST requests to REST APIs",
)


_filesystem_tool = FilesystemTool()


def _execute_filesystem_read(
    name: str, params: dict[str, Any], tool: dict[str, Any]
) -> dict[str, Any]:
    return _filesystem_tool.execute({**params, "_operation": "read"})


def _execute_filesystem_write(
    name: str, params: dict[str, Any], tool: dict[str, Any]
) -> dict[str, Any]:
    return _filesystem_tool.execute({**params, "_operation": "write"})


def _execute_filesystem_grep(
    name: str, params: dict[str, Any], tool: dict[str, Any]
) -> dict[str, Any]:
    return _filesystem_tool.execute({**params, "_operation": "grep"})


def _execute_filesystem_glob(
    name: str, params: dict[str, Any], tool: dict[str, Any]
) -> dict[str, Any]:
    return _filesystem_tool.execute({**params, "_operation": "glob"})


registry.register(
    name="filesystem.read",
    execute_fn=_execute_filesystem_read,
    description="Read file contents from the local filesystem",
)
registry.register(
    name="filesystem.write",
    execute_fn=_execute_filesystem_write,
    description="Write content to a file on the local filesystem",
)
registry.register(
    name="filesystem.grep",
    execute_fn=_execute_filesystem_grep,
    description="Search for a regex pattern across files in a directory",
)
registry.register(
    name="filesystem.glob",
    execute_fn=_execute_filesystem_glob,
    description="Discover files matching a glob pattern",
)


_shell_tool = ShellTool()


def _execute_shell_exec(
    name: str, params: dict[str, Any], tool: dict[str, Any]
) -> dict[str, Any]:
    return _shell_tool.execute(params)


registry.register(
    name="shell.exec",
    execute_fn=_execute_shell_exec,
    description="Execute a shell command with timeout and output capture",
)


__all__ = [
    "MCPClientConfig",
    "MCPServerTool",
    "ToolRegistry",
    "MCPClientManager",
    "registry",
    "mcp_manager",
    "HTTPTool",
    "FilesystemTool",
    "ShellTool",
]
