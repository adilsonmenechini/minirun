"""Session Replay — reconstruct a session timeline from the Event Journal.

Replays a session by reading its events from the journal and assembling
a human-readable timeline of what happened, in order.  No LLM provider
is called — the replay uses only stored event data.

Usage::

    replay = SessionReplay(journal)
    timeline = replay.reconstruct("session-uuid-here")
    print(replay.format_timeline(timeline))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minirun.log import get_logger
from minirun.memory import (
    PROFILE_LOADED,
    PROVIDER_CALLED,
    RESPONSE_GENERATED,
    SESSION_STARTED,
    SUMMARY_GENERATED,
    TOOL_CONFIRMATION_REQUIRED,
    TOOL_DENIED,
    TOOL_EXECUTED,
    TOOL_REQUESTED,
    EventJournal,
)

log = get_logger("metrics.replay")


# ── Data contracts ──────────────────────────────────────────────────────


@dataclass
class TimelineEntry:
    """A single entry in the reconstructed session timeline.

    Attributes:
        timestamp: ISO-8601 timestamp (trimmed to seconds).
        event_type: The raw event type constant.
        summary: Human-readable one-line summary of what happened.
        icon: A single-character icon for visual grouping.
        details: Optional multi-line details (tool output, response text).
        event_id: UUID of the originating event.
        parent_id: Optional causal parent event UUID.
    """

    timestamp: str
    event_type: str
    summary: str
    icon: str = ""
    details: str = ""
    event_id: str = ""
    parent_id: str | None = None


@dataclass
class ReconstructedSession:
    """A fully reconstructed session from journal events.

    Attributes:
        session_id: UUID of the session.
        provider: Provider name (from SESSION_STARTED payload).
        model: Model name (from SESSION_STARTED payload).
        profile: Profile name (from PROFILE_LOADED payload).
        num_events: Total event count for this session.
        entries: Chronological timeline entries.
        duration_ms: Estimated session duration in milliseconds
            (from first to last event timestamp).
        summary: Session summary text (from SUMMARY_GENERATED payload).
    """

    session_id: str
    provider: str = ""
    model: str = ""
    profile: str = ""
    num_events: int = 0
    entries: list[TimelineEntry] = field(default_factory=list)
    duration_ms: float = 0.0
    summary: str = ""


# ── Icon mapping ────────────────────────────────────────────────────────

_EVENT_ICONS: dict[str, str] = {
    SESSION_STARTED: "▶",
    PROFILE_LOADED: "⚙",
    PROVIDER_CALLED: "→",
    TOOL_REQUESTED: "🔍",
    TOOL_DENIED: "⛔",
    TOOL_CONFIRMATION_REQUIRED: "⚠",
    TOOL_EXECUTED: "✓",
    RESPONSE_GENERATED: "💬",
    SUMMARY_GENERATED: "📝",
}

_DEFAULT_ICON = "•"


# ── SessionReplay ───────────────────────────────────────────────────────


class SessionReplay:
    """Reconstruct a session timeline from the Event Journal.

    Reads all events for a given session ID and assembles them into
    a chronological :class:`ReconstructedSession` with human-readable
    summaries for each step.
    """

    def __init__(self, journal: EventJournal) -> None:
        self._journal = journal

    # ── Reconstruction ─────────────────────────────────────────────────

    def reconstruct(self, session_id: str) -> ReconstructedSession:
        """Reconstruct a session from its journal events.

        Args:
            session_id: UUID of the session to replay.

        Returns:
            A :class:`ReconstructedSession` with all timeline entries.

        Raises:
            ValueError: If the session has no events in the journal.
        """
        events = self._journal.get_session_events(session_id)
        if not events:
            msg = f"Session {session_id} not found in journal"
            raise ValueError(msg)

        session = ReconstructedSession(session_id=session_id)
        session.num_events = len(events)

        for ev in events:
            ts = (ev.get("timestamp") or "")[:19]
            etype = ev.get("event_type", "")
            payload = ev.get("payload", {}) or {}
            eid = ev.get("id", "")[:8]
            pid = ev.get("parent_id")

            entry = self._build_entry(ts, etype, payload, eid, pid)
            session.entries.append(entry)

            # Extract metadata from specific event types
            if etype == SESSION_STARTED:
                session.provider = payload.get("provider", "")
                session.model = payload.get("model", "")
            elif etype == PROFILE_LOADED:
                session.profile = payload.get("profile", "")
            elif etype == SUMMARY_GENERATED:
                session.summary = payload.get("prompt", "")[:120]

        # Compute approximate duration
        if len(events) >= 2:
            first_ts = (events[0].get("timestamp") or "")[:19]
            last_ts = (events[-1].get("timestamp") or "")[:19]
            session.duration_ms = _estimate_duration_ms(first_ts, last_ts)

        return session

    # ── Entry builder ─────────────────────────────────────────────────

    def _build_entry(
        self,
        ts: str,
        etype: str,
        payload: dict[str, Any],
        eid: str,
        pid: str | None,
    ) -> TimelineEntry:
        """Build a single TimelineEntry from an event."""
        icon = _EVENT_ICONS.get(etype, _DEFAULT_ICON)

        if etype == SESSION_STARTED:
            provider = payload.get("provider", "?")
            model = payload.get("model", "?")
            resumed = payload.get("resumed", False)
            resumed_str = " (resumed)" if resumed else ""
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=(
                    f"Session started — provider={provider}, model={model}{resumed_str}"
                ),
                icon=icon,
                event_id=eid,
                parent_id=pid,
            )

        if etype == PROFILE_LOADED:
            profile = payload.get("profile", "?")
            servers = payload.get("mcp_servers", 0)
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Profile loaded: @{profile} ({servers} MCP server(s))",
                icon=icon,
                event_id=eid,
                parent_id=pid,
            )

        if etype == PROVIDER_CALLED:
            n_msgs = payload.get("num_messages", "?")
            provider = payload.get("provider", "?")
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Provider called — {provider}, {n_msgs} message(s) in context",
                icon=icon,
                event_id=eid,
                parent_id=pid,
            )

        if etype == TOOL_REQUESTED:
            tool = payload.get("tool", "?")
            decision = payload.get("decision", "?")
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Tool requested: {tool} (decision={decision})",
                icon=icon,
                event_id=eid,
                parent_id=pid,
            )

        if etype == TOOL_DENIED:
            tool = payload.get("tool", "?")
            reason = payload.get("reason", "?")
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Tool denied: {tool} — {reason}",
                icon=icon,
                event_id=eid,
                parent_id=pid,
                details=f"Reason: {reason}",
            )

        if etype == TOOL_CONFIRMATION_REQUIRED:
            tool = payload.get("tool", "?")
            reason = payload.get("reason", "")
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Tool confirmation required: {tool} — {reason}",
                icon=icon,
                event_id=eid,
                parent_id=pid,
                details=f"Reason: {reason}",
            )

        if etype == TOOL_EXECUTED:
            tool = payload.get("tool", "?")
            latency = payload.get("latency_ms")
            latency_str = f" in {latency:.1f}ms" if latency is not None else ""
            result_raw = payload.get("result", "")
            # Truncate result for preview
            result_preview = str(result_raw)[:150] if result_raw else ""
            details = ""
            if result_preview:
                details = f"Result: {result_preview}"
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Tool executed: {tool}{latency_str}",
                icon=icon,
                event_id=eid,
                parent_id=pid,
                details=details,
            )

        if etype == RESPONSE_GENERATED:
            length = payload.get("content_length", "?")
            finish = payload.get("finish_reason", "")
            finish_str = f" ({finish})" if finish else ""
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Response generated — {length} char(s){finish_str}",
                icon=icon,
                event_id=eid,
                parent_id=pid,
            )

        if etype == SUMMARY_GENERATED:
            prompt = payload.get("prompt", "")[:80]
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"Summary: {prompt}",
                icon=icon,
                event_id=eid,
                parent_id=pid,
            )

        if etype == "state_transition":
            from_state = payload.get("from", "?")
            to_state = payload.get("to", "?")
            count = payload.get("count", "?")
            return TimelineEntry(
                timestamp=ts,
                event_type=etype,
                summary=f"State transition #{count}: {from_state} → {to_state}",
                icon=icon,
                event_id=eid,
                parent_id=pid,
            )

        # Fallback for unknown event types
        return TimelineEntry(
            timestamp=ts,
            event_type=etype,
            summary=f"Event: {etype}",
            icon=icon,
            event_id=eid,
            parent_id=pid,
            details=str(payload) if payload else "",
        )

    # ── Formatting ────────────────────────────────────────────────────

    def format_timeline(
        self,
        session: ReconstructedSession,
        show_details: bool = True,
    ) -> str:
        """Format a reconstructed session as a human-readable timeline.

        Args:
            session: The reconstructed session to format.
            show_details: If True, include tool results and other details.

        Returns:
            A formatted string ready for ``print()``.
        """
        lines: list[str] = []
        duration_str = f" — {session.duration_ms:.0f}ms" if session.duration_ms else ""

        lines.append(f"Replay: {session.session_id[:8]}{duration_str}")
        lines.append("─" * 60)
        if session.provider:
            lines.append(f"  {session.provider} {session.model}")
        if session.profile:
            lines.append(f"  @{session.profile}")
        lines.append(f"  events={session.num_events}")
        if session.summary:
            lines.append(f"  {session.summary}")
        lines.append("")

        for i, entry in enumerate(session.entries):
            num = f"{i + 1:3d}"
            timestamp = entry.timestamp or " " * 19
            icon = entry.icon or " "
            summary = entry.summary

            lines.append(f"{num}  {timestamp}  {icon}  {summary}")

            if show_details and entry.details:
                for det_line in entry.details.split("\n"):
                    lines.append(f"     {det_line}")

        lines.append("")
        lines.append(f"(end — {session.num_events} events)")

        return "\n".join(lines)


# ── Helpers ─────────────────────────────────────────────────────────────


def _estimate_duration_ms(ts1: str, ts2: str) -> float:
    """Estimate duration in ms between two ISO-8601 timestamps."""
    from datetime import datetime

    try:
        delta = datetime.fromisoformat(ts2) - datetime.fromisoformat(ts1)
        return max(0.0, delta.total_seconds() * 1000)
    except (ValueError, TypeError):
        return 0.0
