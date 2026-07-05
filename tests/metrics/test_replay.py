"""Tests for SessionReplay — reconstruct session timelines from the Event Journal."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from minirun.memory import (
    PROFILE_LOADED,
    PROVIDER_CALLED,
    RESPONSE_GENERATED,
    SESSION_STARTED,
    SUMMARY_GENERATED,
    TOOL_DENIED,
    TOOL_EXECUTED,
    TOOL_REQUESTED,
    EventJournal,
)
from minirun.metrics.replay import (
    ReconstructedSession,
    SessionReplay,
    TimelineEntry,
    _estimate_duration_ms,
)

# ── Helpers ─────────────────────────────────────────────────────────────


def _seed_replay_session(db_path: Path) -> tuple[str, EventJournal]:
    """Create a journal with a complete session replay dataset."""
    journal = EventJournal(db_path=db_path)
    sid = str(uuid.uuid4())

    journal.emit(
        sid,
        SESSION_STARTED,
        {
            "provider": "openai",
            "model": "gpt-4o",
        },
    )
    journal.emit(
        sid,
        PROFILE_LOADED,
        {
            "profile": "sre",
            "mcp_servers": 2,
        },
    )
    journal.emit(
        sid,
        PROVIDER_CALLED,
        {
            "num_messages": 3,
            "provider": "openai",
            "model": "gpt-4o",
        },
    )
    journal.emit(
        sid,
        TOOL_REQUESTED,
        {
            "tool": "http.get",
            "decision": 1,
        },
    )
    journal.emit(
        sid,
        TOOL_EXECUTED,
        {
            "tool": "http.get",
            "latency_ms": 450.2,
            "result": '{"status": 200, "data": "ok"}',
        },
    )
    journal.emit(
        sid,
        RESPONSE_GENERATED,
        {
            "content_length": 520,
            "finish_reason": "stop",
        },
    )
    journal.emit(
        sid,
        SUMMARY_GENERATED,
        {
            "prompt": "check monitors status",
        },
    )

    return sid, journal


# ── SessionReplay ───────────────────────────────────────────────────────


class TestSessionReplay:
    """Test the SessionReplay class."""

    def test_reconstruct_returns_session(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "r1.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)

        assert isinstance(session, ReconstructedSession)
        assert session.session_id == sid

    def test_reconstruct_has_all_events(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "r2.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)

        assert session.num_events == 7  # 7 events seeded
        assert len(session.entries) == 7

    def test_reconstruct_extracts_metadata(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "r3.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)

        assert session.provider == "openai"
        assert session.model == "gpt-4o"
        assert session.profile == "sre"
        assert "check monitors" in session.summary

    def test_reconstruct_timeline_order(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "r4.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)

        types = [e.event_type for e in session.entries]
        assert types == [
            SESSION_STARTED,
            PROFILE_LOADED,
            PROVIDER_CALLED,
            TOOL_REQUESTED,
            TOOL_EXECUTED,
            RESPONSE_GENERATED,
            SUMMARY_GENERATED,
        ]

    def test_reconstruct_unknown_session(self, tmp_path: Path) -> None:
        db = tmp_path / "r5.sqlite"
        journal = EventJournal(db_path=db)
        replay = SessionReplay(journal)

        import pytest

        with pytest.raises(ValueError, match="not found"):
            replay.reconstruct("nonexistent-session")

    def test_reconstruct_empty_journal(self, tmp_path: Path) -> None:
        db = tmp_path / "r6.sqlite"
        EventJournal(db_path=db)
        SessionReplay(EventJournal(db_path=db))

        import pytest

        # The default path won't match the temp db, so let's construct
        # a journal at the known path
        journal2 = EventJournal(db_path=db)
        replay2 = SessionReplay(journal2)

        with pytest.raises(ValueError, match="not found"):
            replay2.reconstruct("no-such-session")

    def test_entry_has_timestamps(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "r7.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)

        for entry in session.entries:
            assert entry.timestamp != ""
            assert entry.summary != ""

    def test_tool_executed_has_latency(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "r8.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)

        tool_entry = [e for e in session.entries if e.event_type == TOOL_EXECUTED][0]
        assert "450" in tool_entry.summary

    def test_tool_denied_summary(self, tmp_path: Path) -> None:
        db = tmp_path / "r9.sqlite"
        journal = EventJournal(db_path=db)
        sid = str(uuid.uuid4())

        journal.emit(
            sid,
            TOOL_DENIED,
            {
                "tool": "filesystem.write",
                "reason": "denied by policy",
            },
        )

        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)
        entry = session.entries[0]
        assert "filesystem.write" in entry.summary
        assert "denied by policy" in entry.summary


# ── Formatting ──────────────────────────────────────────────────────────


class TestReplayFormatting:
    """Test the format_timeline method."""

    def test_format_includes_header(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "f1.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)
        output = replay.format_timeline(session)

        assert "Replay:" in output
        assert sid[:8] in output
        assert "openai" in output
        assert "gpt-4o" in output
        assert "@sre" in output or "sre" in output

    def test_format_includes_events(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "f2.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)
        output = replay.format_timeline(session)

        # Should contain event type references
        assert "Session started" in output
        assert "Profile loaded" in output
        assert "Provider called" in output
        assert "Tool requested" in output
        assert "Tool executed" in output
        assert "Response generated" in output
        assert "Summary" in output

    def test_format_no_details(self, tmp_path: Path) -> None:
        sid, journal = _seed_replay_session(tmp_path / "f3.sqlite")
        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)
        output = replay.format_timeline(session, show_details=False)

        # Still has basic info
        assert "Replay:" in output

    def test_format_empty_session(self, tmp_path: Path) -> None:
        db = tmp_path / "f4.sqlite"
        journal = EventJournal(db_path=db)
        sid = str(uuid.uuid4())
        journal.emit(sid, SESSION_STARTED, {"provider": "test"})

        replay = SessionReplay(journal)
        session = replay.reconstruct(sid)
        output = replay.format_timeline(session)

        assert "Replay:" in output
        assert sid[:8] in output


# ── ReconstructedSession ────────────────────────────────────────────────


class TestReconstructedSession:
    """Test the ReconstructedSession dataclass."""

    def test_defaults(self) -> None:
        s = ReconstructedSession(session_id="abc-123")
        assert s.session_id == "abc-123"
        assert s.provider == ""
        assert s.num_events == 0
        assert s.entries == []

    def test_with_data(self) -> None:
        s = ReconstructedSession(
            session_id="abc-123",
            provider="anthropic",
            model="claude-3",
            profile="sre",
            num_events=5,
            entries=[
                TimelineEntry(
                    timestamp="2026-07-05T12:00:00",
                    event_type="session_started",
                    summary="Session started",
                    icon="▶",
                )
            ],
        )
        assert s.provider == "anthropic"
        assert len(s.entries) == 1


# ── Duration helper ─────────────────────────────────────────────────────


class TestEstimateDuration:
    """Test the _estimate_duration_ms helper."""

    def test_same_timestamp(self) -> None:
        ts = "2026-07-05T12:00:00"
        assert _estimate_duration_ms(ts, ts) == 0.0

    def test_positive_duration(self) -> None:
        t1 = "2026-07-05T12:00:00"
        t2 = "2026-07-05T12:05:30"
        # 5 min 30 sec = 330000 ms
        assert _estimate_duration_ms(t1, t2) == pytest.approx(330000, abs=100)

    def test_with_timezone(self) -> None:
        t1 = "2026-07-05T12:00:00+00:00"
        t2 = "2026-07-05T12:01:00+00:00"
        # 1 min = 60000 ms
        assert _estimate_duration_ms(t1, t2) == pytest.approx(60000, abs=100)

    def test_invalid_timestamp_returns_zero(self) -> None:
        assert _estimate_duration_ms("invalid", "also-invalid") == 0.0


# ── TimelineEntry ───────────────────────────────────────────────────────


class TestTimelineEntry:
    """Test the TimelineEntry dataclass."""

    def test_defaults(self) -> None:
        e = TimelineEntry(
            timestamp="2026-01-01", event_type="test", summary="test event"
        )
        assert e.icon == ""
        assert e.details == ""
        assert e.parent_id is None

    def test_with_all_fields(self) -> None:
        e = TimelineEntry(
            timestamp="2026-01-01T00:00:00",
            event_type="tool_executed",
            summary="Tool executed: http.get",
            icon="✓",
            details="Result: OK",
            event_id="abc12345",
            parent_id="def56789",
        )
        assert e.event_type == "tool_executed"
        assert e.details == "Result: OK"
        assert e.parent_id == "def56789"
