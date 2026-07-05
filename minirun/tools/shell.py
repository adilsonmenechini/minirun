"""Shell Tool — built-in tool for executing shell commands.

Provides shell command execution using Python's subprocess module.
Gated behind security policy (default-deny).
"""

from __future__ import annotations

import subprocess
from typing import Any

from minirun.log import get_logger

log = get_logger("tools.shell")

DEFAULT_TIMEOUT = 30


class ShellTool:
    """Built-in tool for executing shell commands in a subprocess."""

    name = "shell"
    description = "Execute shell commands with timeout and output capture"

    def execute(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a shell command and return stdout, stderr, and exit code.

        Parameters:
            command (str, required): Shell command to execute.
            timeout (int, optional): Timeout in seconds (default: 30).
        """
        params = params or {}
        command = params.get("command")
        if not command or not isinstance(command, str):
            return {
                "success": False,
                "error": "Missing required parameter: command",
            }

        timeout = params.get("timeout", DEFAULT_TIMEOUT)
        if not isinstance(timeout, (int, float)):
            timeout = DEFAULT_TIMEOUT

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=timeout,
                text=True,
            )

            return {
                "success": result.returncode == 0,
                "data": {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                },
            }

        except subprocess.TimeoutExpired:
            log.warning(
                "Shell command timed out after %ds: %.80s",
                timeout,
                command,
            )
            return {
                "success": False,
                "error": f"Command timed out after {timeout}s",
                "data": {
                    "stdout": "",
                    "stderr": "",
                    "exit_code": -1,
                },
            }

        except FileNotFoundError as exc:
            return {
                "success": False,
                "error": f"Command not found: {exc}",
            }

        except PermissionError as exc:
            return {
                "success": False,
                "error": f"Permission denied: {exc}",
            }

        except OSError as exc:
            log.error("Shell command failed: %s", exc)
            return {
                "success": False,
                "error": f"System error: {exc}",
            }

        except Exception as exc:
            log.error("Unexpected shell error: %s", exc)
            return {
                "success": False,
                "error": str(exc),
            }
