"""Event Journal — SQLite-backed event store for execution observability.

Each interaction is recorded as an immutable event, enabling auditing,
replay, and debugging of the runtime execution.
"""

from __future__ import annotations

import json
import sqlite3
import uuid as uuid_mod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# ── Event type constants ────────────────────────────────────────────────

SESSION_STARTED = "session_started"
PROFILE_LOADED = "profile_loaded"
PROVIDER_CALLED = "provider_called"
TOOL_REQUESTED = "tool_requested"
TOOL_DENIED = "tool_denied"
TOOL_EXECUTED = "tool_executed"
RESPONSE_GENERATED = "response_generated"
SUMMARY_GENERATED = "summary_generated"
STATE_TRANSITION = "state_transition"

EVENT_TYPES = frozenset({
    SESSION_STARTED,
    PROFILE_LOADED,
    PROVIDER_CALLED,
    TOOL_REQUESTED,
    TOOL_DENIED,
    TOOL_EXECUTED,
    RESPONSE_GENERATED,
    SUMMARY_GENERATED,
    STATE_TRANSITION,
})


# ── Default paths ───────────────────────────────────────────────────────

def _default_db_path() -> Path:
    return Path("workspace/memory/journal.sqlite")


# ── EventJournal ────────────────────────────────────────────────────────

class EventJournal:
    """Immutable event store backed by SQLite.

    Events are append-only: once written they are never modified or deleted.
    Each event has an id, session_id, type, timestamp, payload (JSON), and
    an optional parent_event_id for causality chains.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL,
                    event_type  TEXT NOT NULL,
                    timestamp   TEXT NOT NULL,
                    payload     TEXT NOT NULL DEFAULT '{}',
                    parent_id   TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_session "
                "ON events(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_type "
                "ON events(event_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_timestamp "
                "ON events(timestamp DESC)"
            )

    # ── Write ───────────────────────────────────────────────────────────

    def emit(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Append an event to the journal.

        Args:
            session_id: Session this event belongs to.
            event_type: One of the ``EVENT_TYPES`` constants.
            payload: Arbitrary JSON-serialisable metadata.
            parent_id: Optional UUID of the causal parent event.

        Returns:
            The UUID assigned to the new event.
        """
        event_id = str(uuid_mod.uuid4())
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO events (id, session_id, event_type, timestamp,
                                       payload, parent_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    session_id,
                    event_type,
                    now,
                    _json_dumps(payload or {}),
                    parent_id,
                ),
            )
        return event_id

    # ── Query helpers ───────────────────────────────────────────────────

    def get_session_events(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return all events for a session, ordered by timestamp."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id = ? "
                "ORDER BY timestamp ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_events_by_type(
        self,
        event_type: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return events of a specific type, newest first."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM events WHERE event_type = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_recent_events(
        self,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return the most recent events across all sessions."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count_events(self, event_type: str | None = None) -> int:
        """Count events, optionally filtered by type."""
        with sqlite3.connect(self._db_path) as conn:
            if event_type:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM events WHERE event_type = ?",
                    (event_type,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM events"
                ).fetchone()
            return row[0] if row else 0


# ── Helpers ─────────────────────────────────────────────────────────────

def _json_dumps(data: dict[str, Any]) -> str:
    """Serialize dict to JSON string, returning '{}' on failure."""
    try:
        return json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, parsing JSON payload."""
    d: dict[str, Any] = dict(row)
    try:
        d["payload"] = json.loads(d["payload"])
    except (json.JSONDecodeError, TypeError):
        d["payload"] = {}
    return d
