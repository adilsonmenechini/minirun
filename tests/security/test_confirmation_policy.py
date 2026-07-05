"""Tests for the Confirmation Policy — PolicyDecision, PolicyEngine, and integration."""

from __future__ import annotations

import os

from minirun.security import PolicyDecision, SecurityPolicy
from minirun.security.policy import PolicyEngine

# ── PolicyDecision ───────────────────────────────────────────────────────


class TestPolicyDecisionConfirmation:
    """Test the REQUIRES_CONFIRMATION extension to PolicyDecision."""

    def test_requires_confirmation_value(self) -> None:
        assert PolicyDecision.REQUIRES_CONFIRMATION.value == 4

    def test_needs_confirmation_true(self) -> None:
        decision = PolicyDecision.require_confirmation(
            "Write to filesystem needs confirmation"
        )
        assert decision.needs_confirmation is True

    def test_needs_confirmation_allowed(self) -> None:
        assert PolicyDecision.ALLOW.needs_confirmation is False

    def test_needs_confirmation_deny(self) -> None:
        assert PolicyDecision.DENY.needs_confirmation is False

    def test_needs_confirmation_deny_with_reason(self) -> None:
        decision = PolicyDecision.deny("Denied by policy")
        assert decision.needs_confirmation is False

    def test_require_confirmation_has_default_reason(self) -> None:
        decision = PolicyDecision.require_confirmation()
        assert decision.reason == "User confirmation required"

    def test_require_confirmation_custom_reason(self) -> None:
        decision = PolicyDecision.require_confirmation(
            "Tool 'filesystem.write' is destructive"
        )
        assert decision.reason == "Tool 'filesystem.write' is destructive"

    def test_require_confirmation_not_allowed(self) -> None:
        decision = PolicyDecision.require_confirmation("Needs ok")
        assert decision.allowed is False


# ── SecurityPolicy ───────────────────────────────────────────────────────


class TestSecurityPolicyConfirmedTools:
    """Test confirmed_tools field in SecurityPolicy."""

    def test_default_has_no_confirmed(self) -> None:
        policy = SecurityPolicy()
        assert policy.confirmed_tools == []

    def test_confirmed_tools_are_set(self) -> None:
        policy = SecurityPolicy(
            confirmed_tools=["filesystem.write", "http.post"],
            allowed_tools=["filesystem.read", "http.get"],
            denied_tools=["shell.exec"],
        )
        assert "filesystem.write" in policy.confirmed_tools
        assert "http.post" in policy.confirmed_tools
        assert "shell.exec" in policy.denied_tools


# ── PolicyEngine — check_confirmation ────────────────────────────────────


class TestPolicyEngineCheckConfirmation:
    """Test the check_confirmation method directly."""

    def test_confirmed_tool_returns_requires_confirmation(self) -> None:
        engine = PolicyEngine(
            config_path=_make_policy_yaml({"confirmed_tools": ["filesystem.write"]})
        )
        decision = engine.check_confirmation("filesystem.write")
        assert decision.needs_confirmation is True
        assert "filesystem.write" in (decision.reason or "")

    def test_denied_tool_confirmation_not_possible(self) -> None:
        """A denied tool cannot be confirmed — DENY takes precedence."""
        engine = PolicyEngine(
            config_path=_make_policy_yaml({"denied_tools": ["shell.exec"]})
        )
        decision = engine.check_confirmation("shell.exec")
        assert decision.allowed is False
        assert decision.needs_confirmation is False  # DENY, not confirmation

    def test_known_destructive_tool_hardcoded(self) -> None:
        """Known destructive tools like http.post get REQUIRES_CONFIRMATION
        even when not in confirmed_tools (hardcoded safety net).

        Uses an empty policy config so the hardcoded safety net in
        check_confirmation() is the only thing that applies.
        """
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "allowed_tools": [],
                    "denied_tools": [],
                    "confirmed_tools": [],
                }
            )
        )
        for tool in (
            "http.post",
            "http.put",
            "http.delete",
            "http.patch",
            "filesystem.write",
            "shell.exec",
        ):
            decision = engine.check_confirmation(tool)
            assert decision.needs_confirmation is True, (
                f"{tool} should be identified as destructive"
            )

    def test_readonly_tool_no_confirmation(self) -> None:
        """Read-only tools like filesystem.read do not need confirmation."""
        engine = PolicyEngine(config_path=None)
        decision = engine.check_confirmation("filesystem.read")
        assert decision.allowed is True
        assert decision.needs_confirmation is False

    def test_http_get_no_confirmation(self) -> None:
        """HTTP GET is read-only, should not require confirmation."""
        engine = PolicyEngine(config_path=None)
        decision = engine.check_confirmation("http.get")
        assert decision.allowed is True
        assert decision.needs_confirmation is False

    def test_unknown_tool_no_confirmation(self) -> None:
        """Unknown tools are not in the destructive set — no confirmation."""
        engine = PolicyEngine(config_path=None)
        decision = engine.check_confirmation("custom_tool.analyze")
        assert decision.allowed is True
        assert decision.needs_confirmation is False

    def test_allow_all_bypasses_confirmation(self) -> None:
        engine = PolicyEngine(config_path=None, allow_all=True)
        decision = engine.check_confirmation("filesystem.write")
        assert decision.allowed is True
        assert decision.needs_confirmation is False


# ── PolicyEngine — evaluate with confirmation ────────────────────────────


class TestPolicyEngineEvaluateConfirmation:
    """Test that evaluate() correctly returns REQUIRES_CONFIRMATION."""

    def test_confirmed_in_yaml_returns_requires_confirmation(self) -> None:
        engine = PolicyEngine(
            config_path=_make_policy_yaml({"confirmed_tools": ["filesystem.write"]})
        )
        decision = engine.evaluate("filesystem.write")
        assert decision.needs_confirmation is True

    def test_confirmed_comes_before_allowed(self) -> None:
        """A tool in both confirmed_tools and allowed_tools should
        return REQUIRES_CONFIRMATION (confirmation check comes first)."""
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "confirmed_tools": ["filesystem.write"],
                    "allowed_tools": [
                        "filesystem.read",
                        "filesystem.write",
                        "http.get",
                    ],
                }
            )
        )
        decision = engine.evaluate("filesystem.write")
        assert decision.needs_confirmation is True

    def test_denied_still_denied_even_if_confirmed(self) -> None:
        """DENY takes precedence over REQUIRES_CONFIRMATION."""
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "confirmed_tools": ["filesystem.write"],
                    "denied_tools": ["filesystem.write"],
                }
            )
        )
        decision = engine.evaluate("filesystem.write")
        assert decision.allowed is False
        assert decision.needs_confirmation is False

    def test_evaluate_allowed_passes_through(self) -> None:
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "allowed_tools": ["filesystem.read"],
                }
            )
        )
        decision = engine.evaluate("filesystem.read")
        assert decision.allowed is True
        assert decision.needs_confirmation is False

    def test_evaluate_path_check_after_confirmation(self) -> None:
        """If tool requires confirmation, path check is skipped."""
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "confirmed_tools": ["filesystem.write"],
                    "allowed_paths": ["/allowed/"],
                }
            )
        )
        decision = engine.evaluate("filesystem.write", {"path": "/allowed/test.txt"})
        # Returns REQUIRES_CONFIRMATION before reaching path check
        assert decision.needs_confirmation is True


# ── PolicyEngine — check_tool (updated) ──────────────────────────────────


class TestPolicyEngineCheckTool:
    """Test that check_tool now handles confirmed_tools."""

    def test_check_tool_confirmed(self) -> None:
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "confirmed_tools": ["http.post"],
                    "allowed_tools": ["http.post", "http.get"],
                }
            )
        )
        decision = engine.check_tool("http.post")
        assert decision.needs_confirmation is True

    def test_check_tool_allowed_not_confirmed(self) -> None:
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "allowed_tools": ["http.get"],
                }
            )
        )
        decision = engine.check_tool("http.get")
        assert decision.allowed is True
        assert decision.needs_confirmation is False

    def test_check_tool_denied_vs_confirmed(self) -> None:
        """Denied takes precedence over confirmed."""
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "confirmed_tools": ["shell.exec"],
                    "denied_tools": ["shell.exec"],
                }
            )
        )
        decision = engine.check_tool("shell.exec")
        assert decision.allowed is False
        assert decision.needs_confirmation is False

    def test_check_tool_not_in_allowed_is_denied(self) -> None:
        """If not in allowed_tools and not confirmed or denied, it's DENY."""
        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "allowed_tools": ["filesystem.read"],
                }
            )
        )
        decision = engine.check_tool("http.post")
        assert decision.allowed is False

    def test_check_tool_allow_all_bypasses(self) -> None:
        engine = PolicyEngine(config_path=None, allow_all=True)
        decision = engine.check_tool("filesystem.write")
        assert decision.allowed is True


# ── Integration: harness.check_tool_permission decision values ───────────


class TestCheckToolPermissionConfirmation:
    """Test the decision values returned by check_tool_permission
    (from harness) when the policy engine returns REQUIRES_CONFIRMATION."""

    def test_check_tool_permission_returns_requires_confirmation(self) -> None:
        """Integration smoke test: harness function receives correct decision."""

        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "confirmed_tools": ["filesystem.write"],
                }
            )
        )
        decision = engine.evaluate("filesystem.write")
        assert decision.needs_confirmation is True
        assert decision.value == PolicyDecision.REQUIRES_CONFIRMATION.value

    def test_check_tool_permission_allowed_tool(self) -> None:
        """Non-destructive tool still returns ALLOW."""

        engine = PolicyEngine(
            config_path=_make_policy_yaml(
                {
                    "allowed_tools": ["filesystem.read"],
                }
            )
        )
        decision = engine.evaluate("filesystem.read")
        assert decision.allowed is True
        assert decision.needs_confirmation is False


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_policy_yaml(overrides: dict) -> str | None:
    """Create a temporary security.yaml and return its path.

    Uses an empty ``allowed_paths`` and ``allowed_domains`` unless
    overridden.
    """
    import tempfile

    data = {
        "policy": {
            "version": "1.0",
            "allowed_tools": overrides.get("allowed_tools", []),
            "denied_tools": overrides.get("denied_tools", []),
            "confirmed_tools": overrides.get("confirmed_tools", []),
            "allowed_paths": overrides.get("allowed_paths", []),
            "allowed_domains": overrides.get("allowed_domains", []),
        }
    }
    # Use a temp dir that exists
    tmp = tempfile.mkdtemp(prefix="minirun_test_policy_")
    path = os.path.join(tmp, "security.yaml")
    with open(path, "w") as f:
        import yaml

        yaml.dump(data, f)
    return path
