"""Tool executor — policy-gated tool execution with event journaling.

Separates the *execution* concern (permission checks, event emission,
state machine transitions) from the :class:`ToolRegistry` which now
focuses purely on registration and catalog.

Usage::

    executor = ToolExecutor()
    result = await executor.execute(
        tool_name="http.get",
        params={"url": "https://example.com"},
        session_id="abc-123",
        state_machine=sm,
    )
"""

from __future__ import annotations

from typing import Any

from minirun.log import get_logger
from minirun.runtime.events import emit_tool_executed
from minirun.runtime.state import RuntimeState, RuntimeStateMachine
from minirun.security import PolicyDecision
from minirun.tools.registry import ToolRegistry, registry as _default_registry

log = get_logger("runtime.executor")

# Re-export ToolResult for convenience
ToolResult = dict[str, Any]


class ToolExecutor:
    """Policy-gated tool execution with event journaling.

    Wraps a :class:`ToolRegistry` with permission checks and observability.
    """

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self._registry = tool_registry or _default_registry

    @property
    def registry(self) -> ToolRegistry:
        """The underlying tool registry (read-only)."""
        return self._registry

    async def execute(  # noqa: PLR0913 — many params is by design
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        state_machine: RuntimeStateMachine | None = None,
    ) -> ToolResult:
        """Execute a tool with permission checks and event journaling.

        Steps:
        1. Transition to ``EXECUTE_TOOL`` state (if a state machine is
           provided).
        2. Check permission via
           :func:`minirun.runtime.harness.check_tool_permission`.
        3. Look up the tool in the registry.
        4. Call the registered execute function.
        5. Emit a ``TOOL_EXECUTED`` event.

        Args:
            tool_name: Name of the registered tool.
            params: Parameters forwarded to the tool function.
            session_id: Optional session ID for event journaling.
            state_machine: Optional state machine to transition.

        Returns:
            A dict with at least a ``success`` key.
        """
        # ── 1. State machine transition ───────────────────────────────
        if state_machine is not None:
            state_machine.transition(RuntimeState.EXECUTE_TOOL)

        # ── 2. Permission check ───────────────────────────────────────
        from minirun.runtime.harness import check_tool_permission

        decision = check_tool_permission(
            tool_name=tool_name,
            params=params,
            session_id=session_id,
        )
        if decision != PolicyDecision.ALLOW:
            log.warning(
                "Tool %s denied by policy: %s",
                tool_name,
                decision.value,
            )
            return {"success": False, "error": f"Policy denied: {decision.value}"}

        # ── 3. Registry lookup ────────────────────────────────────────
        tool = self._registry.get_tool(tool_name)
        if tool is None:
            log.warning("Unknown tool: %s", tool_name)
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        # ── 4. Execute ────────────────────────────────────────────────
        execute_fn = tool["execute"]
        try:
            result = execute_fn(tool_name, params or {}, tool)
        except Exception as exc:
            log.error("Tool execution failed: %s — %s", tool_name, exc)
            return {"success": False, "error": str(exc)}

        # ── 5. Event journaling ───────────────────────────────────────
        emit_tool_executed(
            tool_name=tool_name,
            result=result,
            session_id=session_id,
        )

        return result
