"""Workspace execution handlers.

Phase 2 responsibilities (plan.md):
- Execute skill tools with configurable timeout (FR-011)
- Restrict handler file access to workspace/ (NFR-004)
- Catch failures and return structured errors (FR-004 / FR-011)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

from minirun.log import get_logger
from minirun.workspace.models import (
    WorkspaceCommand,
    WorkspaceProfile,
    WorkspaceProfileOverride,
    WorkspaceSkill,
)

log = get_logger("workspace.executor")

# ── Defaults (FR-011 / NFR-004) ────────────────────────────────────────

SKILL_TIMEOUT_DEFAULT = 30  # seconds (FR-011)
COMMAND_TIMEOUT_DEFAULT = 30  # seconds (NFR-004)


class WorkspaceExecutor:
    """Executes workspace tools: skills, extensions, and commands.

    Args:
        profile: The workspace profile context for execution.
        workspace_root: Root of the workspace directory used for path
            restriction (NFR-004). Defaults to ``os.getcwd() / workspace/``.
    """

    def __init__(
        self,
        profile: WorkspaceProfile,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.profile = profile
        self._workspace_root = Path(
            workspace_root or os.environ.get("MINIRUN_WORKSPACE", "workspace")
        ).resolve()
        log.debug(
            "WorkspaceExecutor initialized for profile %s (root=%s)",
            profile.name,
            self._workspace_root,
        )

    # ── Path restriction (NFR-004) ─────────────────────────────────────

    def _check_path_allowed(self, file_path: str) -> Path:
        """Resolve a file path and ensure it is inside the workspace root.

        Raises ``PermissionError`` if the path is outside workspace/
        (NFR-004).
        """
        target = Path(file_path).resolve()
        workspace = self._workspace_root

        try:
            target.relative_to(workspace)
        except ValueError:
            raise PermissionError(
                f"NFR-004: access to '{file_path}' is denied — "
                f"skill handlers may only access files under '{workspace}'"
            )
        return target

    # ── Skill tool execution (FR-011) ───────────────────────────────────

    async def execute_skill_tool(
        self,
        skill: WorkspaceSkill,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a skill tool with timeout and path restriction.

        Steps:
        1. Look up the tool by name within the skill.
        2. Determine timeout: skill.timeout or SKILL_TIMEOUT_DEFAULT (30s).
        3. Check the handler path against workspace/ (NFR-004).
        4. Execute the handler.
        5. Return result or structured error (FR-011).

        Args:
            skill: The skill containing the tool.
            tool_name: Name of the tool to execute.
            arguments: Arguments passed to the tool handler.

        Returns:
            Dict with at least ``success`` key.
        """
        # Find the tool
        tool_def = None
        for t in skill.tools:
            if t.name == tool_name:
                tool_def = t
                break

        if tool_def is None:
            return {
                "success": False,
                "error": (f"Skill '{skill.name}': tool '{tool_name}' not found"),
            }

        # Determine timeout (FR-011: configurable, default 30s)
        timeout = skill.timeout or SKILL_TIMEOUT_DEFAULT

        # Parse handler reference
        handler = tool_def.handler
        if not handler:
            return {
                "success": False,
                "error": (f"Skill '{skill.name}'.'{tool_name}' has no handler"),
            }

        try:
            if handler.startswith("python:"):
                return await self._execute_python_handler(
                    skill, tool_name, handler, arguments or {}, timeout
                )
            elif handler.startswith("shell:"):
                return await self._execute_shell_handler(
                    skill, tool_name, handler, arguments or {}, timeout
                )
            elif handler.startswith("mcp:"):
                # MCP handlers delegate to MCPProfileManager
                return {
                    "success": False,
                    "error": (
                        f"MCP handler '{handler}' must be invoked via "
                        f"MCPProfileManager, not WorkspaceExecutor"
                    ),
                }
            else:
                return {
                    "success": False,
                    "error": (
                        f"Unknown handler type in '{handler}' — "
                        f"expected python:, shell:, or mcp:"
                    ),
                }
        except Exception as exc:
            log.error(
                "Skill '%s'.'%s' handler failed: %s",
                skill.name,
                tool_name,
                exc,
            )
            # FR-011 / FR-004: return structured error, never crash
            return {
                "success": False,
                "error": (f"Skill '{skill.name}.{tool_name}' handler failed: {exc}"),
            }

    async def _execute_python_handler(
        self,
        skill: WorkspaceSkill,
        tool_name: str,
        handler: str,
        arguments: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        """Execute a Python handler (e.g., ``python:module.path:function``)."""
        # handler format: "python:module.path:function"
        parts = handler.split(":")
        if len(parts) < 3:
            return {
                "success": False,
                "error": (
                    f"Invalid Python handler '{handler}' — "
                    f"expected format 'python:module.path:function'"
                ),
            }

        module_path = parts[1]
        func_name = parts[2]

        try:
            import importlib

            module = importlib.import_module(module_path)

            # NFR-004: check module file path is within workspace/
            if hasattr(module, "__file__") and module.__file__:
                self._check_path_allowed(module.__file__)

            func = getattr(module, func_name, None)
            if func is None:
                return {
                    "success": False,
                    "error": (
                        f"Function '{func_name}' not found in module '{module_path}'"
                    ),
                }

            result = await asyncio.wait_for(
                asyncio.to_thread(func, **arguments),
                timeout=timeout,
            )
            return {"success": True, "result": result}

        except TimeoutError:
            log.error(
                "Python handler timed out after %ds: %s",
                timeout,
                handler,
            )
            return {
                "success": False,
                "error": (
                    f"Skill '{skill.name}.{tool_name}' "
                    f"handler timed out after {timeout}s"
                ),
            }
        except PermissionError as exc:
            return {"success": False, "error": str(exc)}

    async def _execute_shell_handler(
        self,
        skill: WorkspaceSkill,
        tool_name: str,
        handler: str,
        arguments: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        """Execute a shell handler (e.g., ``shell:command_name``).

        NFR-004: shell-based skill handlers have a 30s execution timeout.
        """
        # handler format: "shell:command_name"
        parts = handler.split(":", 1)
        if len(parts) < 2:
            return {
                "success": False,
                "error": (
                    f"Invalid shell handler '{handler}' — "
                    f"expected format 'shell:command_name'"
                ),
            }

        command_name = parts[1]
        cmd_path = Path(command_name)

        # If it's a relative path, resolve within workspace/commands/
        if not cmd_path.is_absolute():
            cmd_path = self._workspace_root / "commands" / command_name

        # NFR-004: check path is within workspace/
        try:
            resolved = self._check_path_allowed(str(cmd_path))
        except PermissionError as exc:
            return {"success": False, "error": str(exc)}

        args_list = _build_shell_args(arguments)

        log.debug(
            "Executing shell handler: %s %s (timeout=%ds)",
            resolved,
            args_list,
            timeout,
        )
        try:
            result = subprocess.run(
                [str(resolved)] + args_list,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"Command not found: {resolved}",
            }
        except subprocess.TimeoutExpired:
            log.error(
                "Shell handler timed out after %ds: %s",
                timeout,
                handler,
            )
            return {
                "success": False,
                "error": (
                    f"Skill '{skill.name}.{tool_name}' "
                    f"handler timed out after {timeout}s"
                ),
            }

    # ── Command execution (Step 2.8) ───────────────────────────────────

    def execute_command(
        self,
        command: WorkspaceCommand,
        arguments: list[str],
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute a workspace command with NFR-004 timeout.

        Args:
            command: The command to execute.
            arguments: CLI arguments.
            timeout: Override timeout (default: COMMAND_TIMEOUT_DEFAULT).
        """
        actual_timeout = timeout or COMMAND_TIMEOUT_DEFAULT

        log.debug(
            "Executing command: %s %s (timeout=%ds)",
            command.path,
            arguments,
            actual_timeout,
        )
        try:
            result = subprocess.run(
                [command.path] + arguments,
                capture_output=True,
                text=True,
                timeout=actual_timeout,
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
            log.error("Command timeout: %s (%ds)", command.path, actual_timeout)
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"timeout after {actual_timeout}s",
            }

    # ── Override execution ─────────────────────────────────────────────

    def execute_override(
        self,
        override: WorkspaceProfileOverride,
        _task: dict[str, Any],
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


# ── Helpers ────────────────────────────────────────────────────────────


def _build_shell_args(arguments: dict[str, Any]) -> list[str]:
    """Convert a dict of keyword arguments to CLI arguments.

    Simple heuristic: ``{"key": "val"}`` → ``["--key", "val"]``.
    Booleans: ``{"verbose": True}`` → ``["--verbose"]``.
    """
    args: list[str] = []
    for key, value in arguments.items():
        flag = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                args.append(flag)
        else:
            args.extend([flag, str(value)])
    return args
