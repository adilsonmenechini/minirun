"""Workspace execution handlers."""

from __future__ import annotations

from typing import Any

from minirun.log import get_logger
from minirun.workspace.models import (
    WorkspaceCommand,
    WorkspaceProfile,
    WorkspaceProfileOverride,
    WorkspaceSkill,
)

log = get_logger("workspace.executor")


class WorkspaceExecutor:
    """Executes workspace tools: skills, agents, and commands."""

    def __init__(self, profile: WorkspaceProfile) -> None:
        self.profile = profile
        log.debug("WorkspaceExecutor initialized for profile %s", profile.name)

    async def execute_skill_tool(
        self, tool: WorkspaceSkill, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "Use MCPProfileManager.call_tool("
            "server_name, tool_name, arguments) for skill tools"
        )

    def execute_command(
        self, command: WorkspaceCommand, arguments: list[str], timeout: int = 60
    ) -> dict[str, Any]:
        import subprocess

        log.debug("Executing: %s %s", command.path, arguments)
        try:
            result = subprocess.run(
                [command.path] + arguments,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except FileNotFoundError:
            log.error("Command not found: %s", command.path)
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"command not found: {command.path}",
            }
        except subprocess.TimeoutExpired:
            log.error("Command timeout: %s (%ds)", command.path, timeout)
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
            }

    def execute_override(
        self, override: WorkspaceProfileOverride, _task: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a profile override with a task.

        Override execution is delegated to the configured
        runtime (e.g., minirun-turbo harness).
        """
        log.warning(
            "execute_override is a stub; "
            "runtime harness wiring is required for override execution"
        )
        return {"status": "not_implemented", "override": override.name}
