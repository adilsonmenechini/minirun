"""Tests for EventJournal — SQLite-backed event store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from minirun.memory.journal.journal import (
    EVENT_TYPES,
    PROVIDER_CALLED,
    RESPONSE_GENERATED,
    SESSION_STARTED,
    SUMMARY_GENERATED,
    TOOL_DENIED,
    TOOL_EXECUTED,
    TOOL_REQUESTED,
    EventJournal,
)


class TestEventJournal:
    def test_init_creates_schema(self, tmp_path: Path) -> None:
        db = tmp_path / "journal.sqlite"
        journal = EventJournal(db_path=db)
        assert db.exists()
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='events'"
            ).fetchall()
        assert len(rows) == 1

    def test_emit_returns_uuid(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        eid = journal.emit("s1", SESSION_STARTED)
        assert isinstance(eid, str)
        assert len(eid) == 36  # UUID4

    def test_emit_and_retrieve(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        journal.emit("s1", SESSION_STARTED, {"provider": "openai"})
        events = journal.get_session_events("s1")
        assert len(events) == 1
        assert events[0]["session_id"] == "s1"
        assert events[0]["event_type"] == SESSION_STARTED
        assert events[0]["payload"]["provider"] == "openai"

    def test_multiple_events_order(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        journal.emit("s1", SESSION_STARTED)
        journal.emit("s1", PROVIDER_CALLED, {"num_messages": 2})
        journal.emit("s1", RESPONSE_GENERATED, {"content_length": 100})
        events = journal.get_session_events("s1")
        assert len(events) == 3
        assert events[0]["event_type"] == SESSION_STARTED
        assert events[1]["event_type"] == PROVIDER_CALLED
        assert events[2]["event_type"] == RESPONSE_GENERATED

    def test_events_by_type(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        journal.emit("s1", SESSION_STARTED)
        journal.emit("s1", PROVIDER_CALLED)
        journal.emit("s2", SESSION_STARTED)
        session_starts = journal.get_events_by_type(SESSION_STARTED)
        assert len(session_starts) == 2

    def test_events_by_type_empty(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        assert journal.get_events_by_type("nonexistent") == []

    def test_recent_events(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        for i in range(5):
            journal.emit(f"s{i}", SESSION_STARTED)
        recent = journal.get_recent_events(limit=3)
        assert len(recent) == 3

    def test_count_events(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        assert journal.count_events() == 0
        journal.emit("s1", SESSION_STARTED)
        journal.emit("s1", PROVIDER_CALLED)
        assert journal.count_events() == 2
        assert journal.count_events(SESSION_STARTED) == 1
        assert journal.count_events(PROVIDER_CALLED) == 1

    def test_parent_id_chain(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        parent = journal.emit("s1", PROVIDER_CALLED)
        child = journal.emit("s1", RESPONSE_GENERATED, parent_id=parent)
        events = journal.get_session_events("s1")
        assert events[1]["parent_id"] == parent

    def test_payload_serialization(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        payload = {"key": "value", "num": 42, "nested": {"a": 1}}
        journal.emit("s1", SESSION_STARTED, payload=payload)
        events = journal.get_session_events("s1")
        assert events[0]["payload"] == payload

    def test_session_scoped(self, tmp_path: Path) -> None:
        journal = EventJournal(db_path=tmp_path / "j.sqlite")
        journal.emit("s1", SESSION_STARTED)
        journal.emit("s2", SESSION_STARTED)
        journal.emit("s2", PROVIDER_CALLED)
        assert len(journal.get_session_events("s1")) == 1
        assert len(journal.get_session_events("s2")) == 2

    def test_default_db_path_creates_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "minirun.memory.journal.journal._default_db_path",
            lambda: tmp_path / "custom" / "journal.sqlite",
        )
        journal = EventJournal()
        assert journal._db_path.parent.exists()


class TestEventTypes:
    def test_all_types_in_frozenset(self) -> None:
        expected = {
            "session_started",
            "profile_loaded",
            "provider_called",
            "tool_requested",
            "tool_denied",
            "tool_executed",
            "response_generated",
            "summary_generated",
            "state_transition",
        }
        assert EVENT_TYPES == expected

    def test_constants_match(self) -> None:
        assert SESSION_STARTED == "session_started"
        assert PROVIDER_CALLED == "provider_called"
        assert RESPONSE_GENERATED == "response_generated"
        assert SUMMARY_GENERATED == "summary_generated"
        assert TOOL_REQUESTED == "tool_requested"
        assert TOOL_DENIED == "tool_denied"
        assert TOOL_EXECUTED == "tool_executed"
