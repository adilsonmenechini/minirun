"""Policy Engine — enforces security policies for tool invocation.

Every tool invocation MUST pass through the Policy Engine before execution
(Constitution Principle V). The engine evaluates calls against rules defined
in config/security.yaml.
"""

from __future__ import annotations

import fnmatch
import os
from urllib.parse import urlparse

import yaml

from minirun.log import get_logger
from minirun.security import PolicyDecision, SecurityPolicy

log = get_logger("security.policy")


class PolicyEngine:
    """Evaluates tool invocation requests against security policies."""

    def __init__(
        self,
        config_path: str | None = None,
        allow_all: bool = False,
    ) -> None:
        self._config_path = config_path or _default_security_config_path()
        self._policy: SecurityPolicy = SecurityPolicy()
        self.allow_all = allow_all
        self._load()

    def _load(self) -> None:
        """Load security policy from YAML file."""
        path = self._config_path
        if not os.path.isfile(path):
            log.info(
                "Security policy not found at %s — using default-deny",
                path,
            )
            self._policy = SecurityPolicy()
            return

        try:
            with open(path) as f:
                data = yaml.safe_load(f)

            if not data or "policy" not in data:
                log.warning("Invalid security policy format — using default-deny")
                self._policy = SecurityPolicy()
                return

            policy_data = data["policy"]
            self._policy = SecurityPolicy(
                version=policy_data.get("version", "1.0"),
                allowed_tools=policy_data.get("allowed_tools", []),
                denied_tools=policy_data.get("denied_tools", []),
                allowed_paths=policy_data.get("allowed_paths", []),
                allowed_domains=policy_data.get("allowed_domains", []),
            )
            log.info(
                "Loaded security policy v%s (%d allowed, %d denied)",
                self._policy.version,
                len(self._policy.allowed_tools),
                len(self._policy.denied_tools),
            )
        except yaml.YAMLError as exc:
            log.error("Failed to parse security policy: %s — using default-deny", exc)
            self._policy = SecurityPolicy()

    def check_tool(self, tool_name: str) -> PolicyDecision:
        """Check if a tool is permitted by the security policy.

        Evaluation order:
        1. If tool_name in denied_tools → DENY
        2. If tool_name not in allowed_tools → DENY
        3. Otherwise → ALLOW
        """
        if self.allow_all:
            return PolicyDecision.ALLOW

        if tool_name in self._policy.denied_tools:
            return PolicyDecision.deny(f"Tool '{tool_name}' is denied by policy")

        if self._policy.allowed_tools:
            if tool_name not in self._policy.allowed_tools:
                return PolicyDecision.deny(
                    f"Tool '{tool_name}' is not in allowed_tools"
                )

        return PolicyDecision.ALLOW

    def check_path(self, tool_name: str, path: str) -> PolicyDecision:
        """Check if a filesystem path is permitted.

        Uses os.path.realpath() to resolve symlinks before matching.
        Path must be a prefix of an allowed_paths entry.
        """
        if self.allow_all:
            return PolicyDecision.ALLOW

        if not self._policy.allowed_paths:
            return PolicyDecision.deny(
                f"Path '{path}' is not allowed (no allowed_paths configured)"
            )

        real_path = os.path.realpath(path)
        for allowed in self._policy.allowed_paths:
            allowed_real = (
                os.path.realpath(allowed) if os.path.exists(allowed) else allowed
            )
            if real_path.startswith(
                allowed_real.rstrip("/") + "/"
            ) or real_path == allowed_real.rstrip("/"):
                return PolicyDecision.ALLOW

        return PolicyDecision.deny(f"Path '{path}' is not allowed by policy")

    def check_domain(self, tool_name: str, domain: str) -> PolicyDecision:
        """Check if an HTTP domain is permitted.

        Supports exact match and wildcard prefix match (e.g., *.datadoghq.com).
        """
        if self.allow_all:
            return PolicyDecision.ALLOW

        if not self._policy.allowed_domains:
            return PolicyDecision.deny(
                f"Domain '{domain}' is not allowed (no allowed_domains configured)"
            )

        for allowed in self._policy.allowed_domains:
            if fnmatch.fnmatch(domain, allowed):
                return PolicyDecision.ALLOW

        return PolicyDecision.deny(f"Domain '{domain}' is not allowed by policy")

    def evaluate(
        self,
        tool_name: str,
        params: dict[str, object] | None = None,
    ) -> PolicyDecision:
        """Full evaluation: tool check + path/domain check if applicable.

        This is the primary method called by the runtime.
        """
        # Step 1: Check tool name
        decision = self.check_tool(tool_name)
        if not decision.allowed:
            self._log_denial(tool_name, decision.reason or "denied", params)
            return decision

        params = params or {}

        # Step 2: Check path if present in params
        path = params.get("path")
        if path is not None and isinstance(path, str):
            decision = self.check_path(tool_name, path)
            if not decision.allowed:
                self._log_denial(tool_name, decision.reason or "path denied", params)
                return decision

        # Step 3: Check domain if URL present in params
        url = params.get("url")
        if url is not None and isinstance(url, str):
            domain = _extract_domain(url)
            if domain:
                decision = self.check_domain(tool_name, domain)
                if not decision.allowed:
                    self._log_denial(
                        tool_name,
                        decision.reason or "domain denied",
                        params,
                    )
                    return decision

        return PolicyDecision.ALLOW

    def reload(self) -> None:
        """Reload security policy from disk."""
        log.info("Reloading security policy from %s", self._config_path)
        self._load()

    def _log_denial(
        self,
        tool_name: str,
        reason: str,
        params: dict[str, object] | None = None,
    ) -> None:
        """Log a policy denial with context."""
        log.warning(
            "POLICY DENY: tool=%s reason=%s params=%s",
            tool_name,
            reason,
            params or {},
        )


def _extract_domain(url: str) -> str | None:
    """Extract the hostname/domain from a URL string."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname:
            return hostname
        return None
    except Exception:
        return None


def _default_security_config_path() -> str:
    """Return the default path to the security configuration file."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config",
        "security.yaml",
    )
