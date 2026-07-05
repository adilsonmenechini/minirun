"""Event journal — global event store and emission helpers.

Extracted from :mod:`minirun.runtime.harness` to isolate the event
journal lifecycle.  Owns the ``_journal`` global singleton.
"""

from __future__ import annotations

from typing import Any

from minirun.log import get_logger
from minirun.memory import EventJournal

log = get_logger("runtime.events")

# Global journal instance initialised by bootstrap()
_journal: EventJournal | None = None


# ── Lifecycle ───────────────────────────────────────────────────────────


def init_journal() -> None:
    """Create the global EventJournal instance.

    Safe to call multiple times — subsequent calls are no-ops when the
    journal is already initialised.
    """
    global _journal
    if _journal is not None:
        return
    _journal = EventJournal()
    log.info("Event Journal initialized")


def get_journal() -> EventJournal:
    """Return the global Event Journal instance."""
    if _journal is None:
        msg = "Event Journal not initialised — call init_journal() first"
        log.error(msg)
        raise RuntimeError(msg)
    return _journal


# ── Emission helpers ────────────────────────────────────────────────────


def safe_emit(
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit an event if the journal is initialised; noop otherwise."""
    if _journal is not None:
        try:
            _journal.emit(
                session_id=session_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            log.warning("Failed to emit event %s", event_type, exc_info=True)


def emit_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    parent_id: str | None = None,
) -> str:
    """Convenience: emit an event via the global journal (raises if uninit)."""
    return get_journal().emit(
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        parent_id=parent_id,
    )


def emit_tool_executed(
    tool_name: str,
    result: Any = None,
    session_id: str | None = None,
) -> None:
    """Emit a TOOL_EXECUTED event after successful tool execution.

    The result is truncated to 200 characters to keep the payload small.
    """
    from minirun.memory import TOOL_EXECUTED

    safe_emit(
        session_id or "system",
        TOOL_EXECUTED,
        payload={"tool": tool_name, "result": str(result)[:200] if result else None},
    )
