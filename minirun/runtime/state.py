"""Runtime state machine — explicit execution loop states.

Replaces the implicit ``while True`` loop with an observable state
machine that transitions through well-defined phases:

    IDLE
     ↓
  BUILD_CONTEXT
     ↓
  CALL_PROVIDER
     ↓
  EXECUTE_TOOL
     ↓
  UPDATE_CONTEXT  ──→  CALL_PROVIDER  (loop for multi-turn)
     ↓
  FINALIZE  (terminal)

Every transition is logged and optionally emitted as a
``STATE_TRANSITION`` event in the :class:`EventJournal`.
"""

from __future__ import annotations

from enum import Enum, auto

from minirun.log import get_logger
from minirun.runtime.events import safe_emit

log = get_logger("runtime.state")


class RuntimeState(Enum):
    """Well-defined phases of the runtime execution loop."""

    IDLE = auto()
    BUILD_CONTEXT = auto()
    CALL_PROVIDER = auto()
    EXECUTE_TOOL = auto()
    UPDATE_CONTEXT = auto()
    FINALIZE = auto()


# ── Transition table ────────────────────────────────────────────────────
# Maps each state → set of valid next states.

_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.IDLE: {RuntimeState.BUILD_CONTEXT},
    RuntimeState.BUILD_CONTEXT: {RuntimeState.CALL_PROVIDER, RuntimeState.FINALIZE},
    RuntimeState.CALL_PROVIDER: {
        RuntimeState.EXECUTE_TOOL,
        RuntimeState.UPDATE_CONTEXT,
        RuntimeState.FINALIZE,  # Allow immediate finalisation (e.g. on interrupt)
    },
    RuntimeState.EXECUTE_TOOL: {RuntimeState.UPDATE_CONTEXT, RuntimeState.FINALIZE},
    RuntimeState.UPDATE_CONTEXT: {RuntimeState.CALL_PROVIDER, RuntimeState.FINALIZE},
    RuntimeState.FINALIZE: set(),
}


def is_valid_transition(current: RuntimeState, next_: RuntimeState) -> bool:
    """Return ``True`` if the transition from *current* → *next_* is valid."""
    return next_ in _TRANSITIONS.get(current, set())


class RuntimeStateMachine:
    """Observable state machine for the runtime execution loop.

    Usage::

        sm = RuntimeStateMachine(session_id="abc")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        # … build context …
        sm.transition(RuntimeState.CALL_PROVIDER)
        # … call provider …
        sm.transition(RuntimeState.FINALIZE)
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._state = RuntimeState.IDLE
        self._transition_count = 0

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def state(self) -> RuntimeState:
        """Current state of the machine."""
        return self._state

    @property
    def session_id(self) -> str:
        """Session ID this machine is bound to."""
        return self._session_id

    @property
    def transition_count(self) -> int:
        """Number of transitions executed so far."""
        return self._transition_count

    # ── Transitions ─────────────────────────────────────────────────────

    def transition(self, new_state: RuntimeState) -> None:
        """Transition to *new_state*, raising if the move is invalid.

        Logs the transition and emits a ``STATE_TRANSITION`` event via
        :func:`minirun.runtime.events.safe_emit`.
        """
        if not is_valid_transition(self._state, new_state):
            msg = f"Invalid state transition: {self._state.name} → {new_state.name}"
            log.error(msg)
            raise RuntimeError(msg)

        old_state = self._state
        self._transition_count += 1
        self._state = new_state

        log.debug(
            "State transition #%d: %s → %s",
            self._transition_count,
            old_state.name,
            new_state.name,
        )

        safe_emit(
            session_id=self._session_id,
            event_type="state_transition",
            payload={
                "from": old_state.name,
                "to": new_state.name,
                "count": self._transition_count,
            },
        )

    def __repr__(self) -> str:
        return (
            f"<RuntimeStateMachine session={self._session_id[:8]} "
            f"state={self._state.name} "
            f"transitions={self._transition_count}>"
        )
