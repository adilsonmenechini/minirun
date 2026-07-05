"""Security module: Policy Engine for runtime tool invocation enforcement.

The Policy Engine evaluates tool calls against security policies defined
in config/security.yaml. Every tool invocation MUST pass through the
Policy Engine before execution (Constitution Principle V).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PolicyDecision(Enum):
    """Result of evaluating a tool invocation against the security policy."""

    ALLOW = 1
    DENY = 2
    DENY_WITH_REASON = 3

    def __init__(self, *args: object) -> None:
        super().__init__()
        self._reason: str | None = None

    @property
    def allowed(self) -> bool:
        return self == PolicyDecision.ALLOW

    @property
    def reason(self) -> str | None:
        return getattr(self, "_reason", None)

    @staticmethod
    def deny(reason: str) -> PolicyDecision:
        decision = PolicyDecision.DENY_WITH_REASON
        decision._reason = reason
        return decision


@dataclass
class SecurityPolicy:
    """Security policy document loaded from config/security.yaml."""

    version: str = "1.0"
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)


from minirun.security.policy import PolicyEngine  # noqa: E402

__all__ = [
    "PolicyDecision",
    "SecurityPolicy",
    "PolicyEngine",
]
