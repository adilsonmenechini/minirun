"""Tests for RuntimeStateMachine — explicit execution loop states."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from minirun.runtime.state import (
    RuntimeState,
    RuntimeStateMachine,
    is_valid_transition,
)


class TestRuntimeState:
    """Enum values are well-defined."""

    def test_all_states_present(self) -> None:
        names = {s.name for s in RuntimeState}
        expected = {
            "IDLE",
            "BUILD_CONTEXT",
            "CALL_PROVIDER",
            "EXECUTE_TOOL",
            "UPDATE_CONTEXT",
            "FINALIZE",
        }
        assert names == expected

    def test_values_are_autos(self) -> None:
        # All values should be unique (auto() guarantees this)
        values = [s.value for s in RuntimeState]
        assert len(values) == len(set(values))


class TestIsValidTransition:
    """Transition table correctness."""

    def test_idle_to_build_context(self) -> None:
        assert is_valid_transition(RuntimeState.IDLE, RuntimeState.BUILD_CONTEXT)

    def test_idle_to_anything_else_invalid(self) -> None:
        for state in RuntimeState:
            if state != RuntimeState.BUILD_CONTEXT:
                assert not is_valid_transition(RuntimeState.IDLE, state)

    def test_build_context_to_call_provider(self) -> None:
        assert is_valid_transition(
            RuntimeState.BUILD_CONTEXT, RuntimeState.CALL_PROVIDER
        )

    def test_build_context_to_finalize(self) -> None:
        """Interrupt during context building → can finalise."""
        assert is_valid_transition(RuntimeState.BUILD_CONTEXT, RuntimeState.FINALIZE)

    def test_build_context_to_other_invalid(self) -> None:
        assert not is_valid_transition(RuntimeState.BUILD_CONTEXT, RuntimeState.IDLE)
        assert not is_valid_transition(
            RuntimeState.BUILD_CONTEXT, RuntimeState.BUILD_CONTEXT
        )

    def test_call_provider_to_execute_or_update_or_finalize(self) -> None:
        assert is_valid_transition(
            RuntimeState.CALL_PROVIDER, RuntimeState.EXECUTE_TOOL
        )
        assert is_valid_transition(
            RuntimeState.CALL_PROVIDER, RuntimeState.UPDATE_CONTEXT
        )
        # Interrupt during provider call
        assert is_valid_transition(RuntimeState.CALL_PROVIDER, RuntimeState.FINALIZE)

    def test_execute_tool_to_update_context_or_finalize(self) -> None:
        assert is_valid_transition(
            RuntimeState.EXECUTE_TOOL, RuntimeState.UPDATE_CONTEXT
        )
        # Interrupt during tool execution
        assert is_valid_transition(RuntimeState.EXECUTE_TOOL, RuntimeState.FINALIZE)

    def test_execute_tool_to_other_invalid(self) -> None:
        assert not is_valid_transition(
            RuntimeState.EXECUTE_TOOL, RuntimeState.CALL_PROVIDER
        )

    def test_update_context_to_call_provider_or_finalize(self) -> None:
        assert is_valid_transition(
            RuntimeState.UPDATE_CONTEXT, RuntimeState.CALL_PROVIDER
        )
        assert is_valid_transition(RuntimeState.UPDATE_CONTEXT, RuntimeState.FINALIZE)

    def test_finalize_is_terminal(self) -> None:
        for state in RuntimeState:
            assert not is_valid_transition(RuntimeState.FINALIZE, state)

    def test_unknown_state_returns_false(self) -> None:
        assert not is_valid_transition(None, RuntimeState.IDLE)  # type: ignore[arg-type]


class TestRuntimeStateMachineInit:
    """Initialisation and property access."""

    def test_default_state_is_idle(self) -> None:
        sm = RuntimeStateMachine(session_id="abc-123")
        assert sm.state == RuntimeState.IDLE

    def test_session_id_stored(self) -> None:
        sm = RuntimeStateMachine(session_id="abc-123")
        assert sm.session_id == "abc-123"

    def test_transition_count_starts_at_zero(self) -> None:
        sm = RuntimeStateMachine(session_id="abc-123")
        assert sm.transition_count == 0

    def test_repr_format(self) -> None:
        sm = RuntimeStateMachine(session_id="abc-123")
        expected = "<RuntimeStateMachine session=abc-123 state=IDLE transitions=0>"
        assert repr(sm) == expected


class TestRuntimeStateMachineTransitions:
    """Valid transition flows."""

    def test_single_transition_updates_state_and_count(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        assert sm.state == RuntimeState.BUILD_CONTEXT
        assert sm.transition_count == 1

    def test_full_pipeline(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        sm.transition(RuntimeState.CALL_PROVIDER)
        sm.transition(RuntimeState.EXECUTE_TOOL)
        sm.transition(RuntimeState.UPDATE_CONTEXT)
        sm.transition(RuntimeState.FINALIZE)
        assert sm.state == RuntimeState.FINALIZE
        assert sm.transition_count == 5

    def test_full_pipeline_skip_execute_tool(self) -> None:
        """The common path: no tool execution."""
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        sm.transition(RuntimeState.CALL_PROVIDER)
        sm.transition(RuntimeState.UPDATE_CONTEXT)
        sm.transition(RuntimeState.FINALIZE)
        assert sm.state == RuntimeState.FINALIZE
        assert sm.transition_count == 4

    def test_multi_turn_loop(self) -> None:
        """Chat loop: BUILD_CONTEXT → CALL_PROVIDER → UPDATE_CONTEXT → (repeat)."""
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        for _ in range(3):
            sm.transition(RuntimeState.CALL_PROVIDER)
            sm.transition(RuntimeState.UPDATE_CONTEXT)
        sm.transition(RuntimeState.FINALIZE)
        assert sm.state == RuntimeState.FINALIZE
        assert sm.transition_count == 8  # 1 build + 6 loop + 1 finalize

    def test_interrupt_from_build_context(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        sm.transition(RuntimeState.FINALIZE)
        assert sm.state == RuntimeState.FINALIZE

    def test_interrupt_from_call_provider(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        sm.transition(RuntimeState.CALL_PROVIDER)
        sm.transition(RuntimeState.FINALIZE)
        assert sm.state == RuntimeState.FINALIZE

    def test_interrupt_from_execute_tool(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        sm.transition(RuntimeState.CALL_PROVIDER)
        sm.transition(RuntimeState.EXECUTE_TOOL)
        sm.transition(RuntimeState.FINALIZE)
        assert sm.state == RuntimeState.FINALIZE


class TestRuntimeStateMachineInvalid:
    """Invalid transitions raise RuntimeError."""

    def test_idle_to_call_provider_invalid(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        with pytest.raises(RuntimeError, match="IDLE → CALL_PROVIDER"):
            sm.transition(RuntimeState.CALL_PROVIDER)

    def test_build_context_to_idle_invalid(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        with pytest.raises(RuntimeError, match="BUILD_CONTEXT → IDLE"):
            sm.transition(RuntimeState.IDLE)

    def test_from_finalize_always_invalid(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        sm.transition(RuntimeState.CALL_PROVIDER)
        sm.transition(RuntimeState.UPDATE_CONTEXT)
        sm.transition(RuntimeState.FINALIZE)
        for state in RuntimeState:
            with pytest.raises(RuntimeError):
                sm.transition(state)

    def test_self_transition_invalid(self) -> None:
        sm = RuntimeStateMachine(session_id="s1")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        with pytest.raises(RuntimeError, match="BUILD_CONTEXT → BUILD_CONTEXT"):
            sm.transition(RuntimeState.BUILD_CONTEXT)


class TestRuntimeStateMachineEventEmission:
    """State transitions emit events via safe_emit."""

    def test_transition_calls_safe_emit(self) -> None:
        with patch("minirun.runtime.state.safe_emit") as mock_emit:
            sm = RuntimeStateMachine(session_id="s1")
            sm.transition(RuntimeState.BUILD_CONTEXT)

            mock_emit.assert_called_once_with(
                session_id="s1",
                event_type="state_transition",
                payload={
                    "from": "IDLE",
                    "to": "BUILD_CONTEXT",
                    "count": 1,
                },
            )

    def test_multiple_transitions_emit_each(self) -> None:
        with patch("minirun.runtime.state.safe_emit") as mock_emit:
            sm = RuntimeStateMachine(session_id="s1")
            sm.transition(RuntimeState.BUILD_CONTEXT)
            sm.transition(RuntimeState.CALL_PROVIDER)

            assert mock_emit.call_count == 2
            # Second call should have count=2
            _, kwargs = mock_emit.call_args
            assert kwargs["payload"]["count"] == 2
            assert kwargs["payload"]["from"] == "BUILD_CONTEXT"
            assert kwargs["payload"]["to"] == "CALL_PROVIDER"

    def test_repr_updates_after_transition(self) -> None:
        sm = RuntimeStateMachine(session_id="abc")
        sm.transition(RuntimeState.BUILD_CONTEXT)
        expected = "<RuntimeStateMachine session=abc state=BUILD_CONTEXT transitions=1>"
        assert repr(sm) == expected
