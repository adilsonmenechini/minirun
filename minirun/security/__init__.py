"""Security module: Policy Engine for runtime tool invocation enforcement.

The Policy Engine evaluates tool calls against security policies defined
in config/security.yaml. Every tool invocation MUST pass through the
Policy Engine before execution (Constitution Principle V).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PolicyDecision(Enum):
    """Result of evaluating a tool invocation against the security policy.

    Attributes:
        ALLOW: Tool is permitted without restrictions.
        DENY: Tool is denied (bare denial, no reason).
        DENY_WITH_REASON: Tool is denied with an explanatory reason.
        REQUIRES_CONFIRMATION: Tool requires explicit user confirmation
            before execution (e.g. destructive operations like write or
            mutation endpoints).
    """

    ALLOW = 1
    DENY = 2
    DENY_WITH_REASON = 3
    REQUIRES_CONFIRMATION = 4

    def __init__(self, *args: object) -> None:
        super().__init__()
        self._reason: str | None = None

    @property
    def allowed(self) -> bool:
        """``True`` only when the decision is ``ALLOW``."""
        return self == PolicyDecision.ALLOW

    @property
    def needs_confirmation(self) -> bool:
        """``True`` when user confirmation should be requested."""
        return self == PolicyDecision.REQUIRES_CONFIRMATION

    @property
    def reason(self) -> str | None:
        return getattr(self, "_reason", None)

    @staticmethod
    def deny(reason: str) -> PolicyDecision:
        decision = PolicyDecision.DENY_WITH_REASON
        decision._reason = reason
        return decision

    @staticmethod
    def require_confirmation(reason: str = "") -> PolicyDecision:
        """Create a ``REQUIRES_CONFIRMATION`` decision with an optional reason."""
        decision = PolicyDecision.REQUIRES_CONFIRMATION
        decision._reason = reason or "User confirmation required"
        return decision


@dataclass
class SecurityPolicy:
    """Security policy document loaded from config/security.yaml."""

    version: str = "1.0"
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    confirmed_tools: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)


from minirun.security.policy import PolicyEngine  # noqa: E402

__all__ = [
    "PolicyDecision",
    "SecurityPolicy",
    "PolicyEngine",
]
