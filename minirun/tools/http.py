"""HTTP Tool — built-in tool for making HTTP requests.

Provides GET and POST request capabilities using Python's standard library
(urllib.request). No external HTTP library required.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from minirun.log import get_logger

log = get_logger("tools.http")

# Default timeout in seconds
DEFAULT_TIMEOUT = 10


class HTTPTool:
    """Built-in tool for making HTTP GET and POST requests."""

    name = "http"
    supported_methods = ["GET", "POST"]
    description = "Makes HTTP GET and POST requests to REST APIs"

    def execute(
        self,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request based on the given parameters."""
        params = params or {}
        method = params.get("method", "GET").upper()
        url = params.get("url")
        headers = params.get("headers", {})
        timeout = params.get("timeout", DEFAULT_TIMEOUT)
        body = params.get("body")

        if not url or not isinstance(url, str):
            return {
                "success": False,
                "error": "Missing required parameter: url",
            }

        if method not in self.supported_methods:
            return {
                "success": False,
                "error": (
                    f"Unsupported method: {method}. Supported: {self.supported_methods}"
                ),
            }

        if not isinstance(timeout, (int, float)):
            timeout = DEFAULT_TIMEOUT

        try:
            result = self._request(method, url, headers, body, int(timeout))
            return result
        except urllib.error.HTTPError as exc:
            log.warning("HTTP %s %s -> %s", method, url, exc.code)
            return {
                "success": False,
                "status_code": exc.code,
                "error": str(exc),
                "body": exc.read().decode("utf-8", errors="replace"),
            }
        except urllib.error.URLError as exc:
            log.warning("HTTP %s %s -> connection error: %s", method, url, exc.reason)
            return {
                "success": False,
                "error": f"Connection error: {exc.reason}",
            }
        except TimeoutError:
            log.warning("HTTP %s %s -> timeout after %ds", method, url, timeout)
            return {
                "success": False,
                "error": f"Request timed out after {timeout}s",
            }
        except Exception as exc:
            log.error("HTTP %s %s -> error: %s", method, url, exc)
            return {
                "success": False,
                "error": str(exc),
            }

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None,
        body: str | None,
        timeout: int,
    ) -> dict[str, Any]:
        """Execute an HTTP request and return structured result."""
        req = urllib.request.Request(url, method=method)

        if headers:
            for key, value in headers.items():
                req.add_header(key, value)

        if method == "POST" and body is not None:
            req.data = body.encode("utf-8")

            if "Content-Type" not in str(req.headers):
                req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            response_headers = dict(response.headers.items())
            response_body = response.read().decode("utf-8", errors="replace")

            # Try to parse as JSON for structured output
            parsed_body: str | dict[str, Any] | list[Any] = response_body
            try:
                parsed_body = json.loads(response_body)
            except (json.JSONDecodeError, ValueError):
                pass

            return {
                "success": True,
                "status_code": status_code,
                "headers": response_headers,
                "body": parsed_body,
            }
