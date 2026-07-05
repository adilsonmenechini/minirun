"""Filesystem Tool — built-in tools for filesystem operations.

Provides read, write, grep, and glob capabilities using Python's standard
library. No external dependencies required.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from minirun.log import get_logger

log = get_logger("tools.filesystem")

DEFAULT_MAX_GLOB_RESULTS = 1000
DEFAULT_GREP_MAX_RESULTS = 100


class FilesystemTool:
    """Built-in tool for filesystem read, write, grep, and glob operations."""

    name = "filesystem"
    description = "Read, write, search, and discover files on the local filesystem"

    def execute(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a filesystem operation based on the _operation parameter."""
        params = params or {}
        operation = params.get("_operation", "")

        handlers: dict[str, Any] = {
            "read": self._read,
            "write": self._write,
            "grep": self._grep,
            "glob": self._glob,
        }

        handler = handlers.get(operation)
        if handler is None:
            return {
                "success": False,
                "error": f"Unknown filesystem operation: {operation}",
            }

        try:
            return handler(params)
        except FileNotFoundError as exc:
            return {"success": False, "error": f"File not found: {exc}"}
        except PermissionError as exc:
            return {"success": False, "error": f"Permission denied: {exc}"}
        except IsADirectoryError as exc:
            return {"success": False, "error": f"Is a directory: {exc}"}
        except NotADirectoryError as exc:
            return {"success": False, "error": f"Not a directory: {exc}"}
        except OSError as exc:
            log.error("Filesystem operation failed: %s", exc)
            return {"success": False, "error": f"Filesystem error: {exc}"}
        except re.error as exc:
            return {"success": False, "error": f"Invalid regex pattern: {exc}"}
        except Exception as exc:
            log.error("Unexpected filesystem error: %s", exc)
            return {"success": False, "error": str(exc)}

    def _read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a file from disk.

        Parameters:
            path (str, required): Path to the file to read.
            encoding (str, optional): File encoding (default: utf-8).
        """
        path = params.get("path")
        if not path or not isinstance(path, str):
            return {"success": False, "error": "Missing required parameter: path"}

        encoding = params.get("encoding", "utf-8")
        if not isinstance(encoding, str):
            encoding = "utf-8"

        target = Path(path)

        if not target.exists():
            return {"success": False, "error": f"File not found: {path}"}

        if not target.is_file():
            return {
                "success": False,
                "error": f"Not a file: {path}",
            }

        # Try reading with specified encoding, fall back to base64 for binary
        try:
            content = target.read_text(encoding=encoding)
            return {"success": True, "data": content, "encoding": encoding}
        except (UnicodeDecodeError, LookupError):
            # Binary file or unknown encoding — fall back to base64
            raw = target.read_bytes()
            encoded = base64.b64encode(raw).decode("ascii")
            return {
                "success": True,
                "data": encoded,
                "encoding": "base64",
                "note": "File content is base64-encoded (binary or wrong encoding)",
            }

    def _write(self, params: dict[str, Any]) -> dict[str, Any]:
        """Write content to a file.

        Parameters:
            path (str, required): Path to the file to write.
            content (str, required): Content to write.
            create_parents (bool, optional): Create parent directories (default: false).
        """
        path = params.get("path")
        if not path or not isinstance(path, str):
            return {"success": False, "error": "Missing required parameter: path"}

        content = params.get("content")
        if content is None or not isinstance(content, str):
            return {"success": False, "error": "Missing required parameter: content"}

        create_parents = params.get("create_parents", False)
        if not isinstance(create_parents, bool):
            create_parents = False

        target = Path(path)

        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(content)
        log.info("Wrote %d bytes to %s", len(content), path)
        return {
            "success": True,
            "data": {"path": str(target), "bytes": len(content)},
        }

    def _grep(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search for a regex pattern across files in a directory.

        Parameters:
            pattern (str, required): Regex pattern to search for.
            path (str, required): Directory path to search within.
            max_results (int, optional): Maximum results (default: 100).
        """
        pattern_str = params.get("pattern")
        if not pattern_str or not isinstance(pattern_str, str):
            return {
                "success": False,
                "error": "Missing required parameter: pattern",
            }

        path = params.get("path")
        if not path or not isinstance(path, str):
            return {"success": False, "error": "Missing required parameter: path"}

        max_results = params.get("max_results", DEFAULT_GREP_MAX_RESULTS)
        if not isinstance(max_results, int):
            max_results = DEFAULT_GREP_MAX_RESULTS

        root = Path(path)
        if not root.is_dir():
            return {"success": False, "error": f"Directory not found: {path}"}

        compiled = re.compile(pattern_str)
        results: list[dict[str, Any]] = []

        for entry in sorted(root.rglob("*")):
            if not entry.is_file():
                continue
            if len(results) >= max_results:
                break
            try:
                # Try reading as text; skip binary files
                for i, line in enumerate(
                    entry.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if compiled.search(line):
                        results.append(
                            {
                                "file": str(entry),
                                "line": i,
                                "content": line,
                            }
                        )
                        if len(results) >= max_results:
                            break
            except (PermissionError, OSError):
                continue

        return {
            "success": True,
            "data": results,
            "matches": len(results),
        }

    def _glob(self, params: dict[str, Any]) -> dict[str, Any]:
        """Discover files matching a glob pattern.

        Parameters:
            pattern (str, required): Glob pattern (e.g., '**/*.md').
            root (str, optional): Root directory (default: '.').
        """
        pattern_str = params.get("pattern")
        if not pattern_str or not isinstance(pattern_str, str):
            return {
                "success": False,
                "error": "Missing required parameter: pattern",
            }

        root_str = params.get("root", ".")
        if not isinstance(root_str, str):
            root_str = "."

        root = Path(root_str)

        if not root.is_dir():
            return {"success": False, "error": f"Directory not found: {root_str}"}

        # Path.glob() natively supports **/ for recursive matching
        matches = sorted(root.glob(pattern_str))

        # Filter to files only and cap results
        files = [str(m) for m in matches if m.is_file()]
        capped = files[:DEFAULT_MAX_GLOB_RESULTS]
        truncated = len(files) > DEFAULT_MAX_GLOB_RESULTS

        return {
            "success": True,
            "data": capped,
            "total": len(capped),
            "truncated": truncated,
        }
