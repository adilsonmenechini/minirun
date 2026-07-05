"""Tests for the Policy Engine module."""

from __future__ import annotations

from minirun.security import PolicyDecision, SecurityPolicy


class TestPolicyDecision:
    """Test the PolicyDecision enum."""

    def test_allow(self) -> None:
        assert PolicyDecision.ALLOW.allowed is True

    def test_deny(self) -> None:
        assert PolicyDecision.DENY.allowed is False

    def test_deny_with_reason(self) -> None:
        decision = PolicyDecision.deny("Tool is denied by policy")
        assert decision.allowed is False
        assert decision.reason == "Tool is denied by policy"

    def test_allow_has_no_reason(self) -> None:
        assert PolicyDecision.ALLOW.reason is None


class TestSecurityPolicy:
    """Test the SecurityPolicy dataclass."""

    def test_default_policy(self) -> None:
        policy = SecurityPolicy()
        assert policy.version == "1.0"
        assert policy.allowed_tools == []
        assert policy.denied_tools == []
        assert policy.allowed_paths == []
        assert policy.allowed_domains == []

    def test_custom_policy(self) -> None:
        policy = SecurityPolicy(
            version="1.0",
            allowed_tools=["filesystem.read", "http.get"],
            denied_tools=["filesystem.write"],
            allowed_paths=["workspace/"],
            allowed_domains=["api.github.com"],
        )
        assert "filesystem.read" in policy.allowed_tools
        assert "filesystem.write" in policy.denied_tools


# Basic import and structure tests
class TestPolicyModule:
    """Test that the security module is importable and has expected exports."""

    def test_module_imports(self) -> None:
        from minirun.security import PolicyEngine  # noqa: F811

        assert PolicyEngine is not None
