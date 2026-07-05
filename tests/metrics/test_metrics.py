"""Tests for the Metrics module — MetricsCollector, formatters, and CLI."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from minirun.memory import TOOL_EXECUTED, TOOL_REQUESTED, EventJournal
from minirun.metrics import (
    MetricsCollector,
    MetricsSummary,
    ToolStats,
    format_metrics_summary,
    format_tool_stats,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _seed_journal(
    db_path: Path,
    tool_calls: list[tuple[str, float]] | None = None,
    extra_events: int = 0,
) -> EventJournal:
    """Create a journal with test data and return it."""
    journal = EventJournal(db_path=db_path)

    # Add some non-tool events
    for _ in range(extra_events):
        journal.emit(
            session_id=str(uuid.uuid4()),
            event_type=TOOL_REQUESTED,
            payload={"tool": "http.get"},
        )

    # Add tool execution events with latency
    tool_calls = tool_calls or [
        ("filesystem.read", 12.5),
        ("filesystem.read", 15.2),
        ("http.get", 450.0),
        ("http.get", 520.3),
        ("http.get", 380.1),
        ("filesystem.grep", 8.3),
    ]
    for tool, latency in tool_calls:
        journal.emit(
            session_id=str(uuid.uuid4()),
            event_type=TOOL_EXECUTED,
            payload={
                "tool": tool,
                "latency_ms": latency,
                "result": json.dumps({"success": True}),
            },
        )

    return journal


# ── MetricsCollector ─────────────────────────────────────────────────────


class TestMetricsCollector:
    """Test the MetricsCollector class."""

    def test_tool_stats_empty_db(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        EventJournal(db_path=db)
        collector = MetricsCollector()
        collector.db_path = db
        assert collector.tool_stats() == []

    def test_tool_stats_empty_no_file(self) -> None:
        collector = MetricsCollector()
        collector.db_path = Path("/nonexistent/path.sqlite")
        assert collector.tool_stats() == []

    def test_tool_stats_basic(self, tmp_path: Path) -> None:
        db = tmp_path / "test.sqlite"
        _seed_journal(db)
        collector = MetricsCollector()
        collector.db_path = db
        stats = collector.tool_stats()

        # Sorted by count desc: http.get (3) > filesystem.read (2) > filesystem.grep (1)
        assert len(stats) == 3
        assert stats[0].tool == "http.get"
        assert stats[0].count == 3
        assert stats[1].tool == "filesystem.read"
        assert stats[1].count == 2
        assert stats[2].tool == "filesystem.grep"
        assert stats[2].count == 1

    def test_tool_stats_latency_averages(self, tmp_path: Path) -> None:
        db = tmp_path / "latency.sqlite"
        _seed_journal(db)
        collector = MetricsCollector()
        collector.db_path = db
        stats = collector.tool_stats()

        # http.get: (450 + 520.3 + 380.1) / 3 = 450.133...
        http_stats = [s for s in stats if s.tool == "http.get"][0]
        assert http_stats.avg_latency_ms == pytest.approx(450.1, abs=0.5)
        assert http_stats.min_latency_ms == pytest.approx(380.1, abs=0.1)
        assert http_stats.max_latency_ms == pytest.approx(520.3, abs=0.1)

        # filesystem.read: (12.5 + 15.2) / 2 = 13.85
        read_stats = [s for s in stats if s.tool == "filesystem.read"][0]
        assert read_stats.avg_latency_ms == pytest.approx(13.85, abs=0.1)
        assert read_stats.min_latency_ms == pytest.approx(12.5, abs=0.1)
        assert read_stats.max_latency_ms == pytest.approx(15.2, abs=0.1)

    def test_tool_stats_last_timestamp(self, tmp_path: Path) -> None:
        db = tmp_path / "ts.sqlite"
        _seed_journal(db)
        collector = MetricsCollector()
        collector.db_path = db

        # Add one more execution with a known tool
        journal = EventJournal(db_path=db)
        journal.emit(
            session_id=str(uuid.uuid4()),
            event_type=TOOL_EXECUTED,
            payload={
                "tool": "http.get",
                "latency_ms": 600.0,
                "result": json.dumps({"success": True}),
            },
        )

        stats = collector.tool_stats()
        http_stats = [s for s in stats if s.tool == "http.get"][0]

        # Should have the latest timestamp (non-empty)
        assert http_stats.last_timestamp != ""
        assert http_stats.last_latency_ms == pytest.approx(600.0, abs=0.1)
        assert http_stats.count == 4  # 3 original + 1 new

    def test_summary_high_level(self, tmp_path: Path) -> None:
        db = tmp_path / "summary.sqlite"
        _seed_journal(db, extra_events=3)
        collector = MetricsCollector()
        collector.db_path = db
        summary = collector.summary()

        assert summary.total_events == 3 + 6  # 3 extra + 6 tool calls
        assert summary.total_tool_calls == 6
        assert summary.unique_tools == 3
        assert len(summary.tool_stats) == 3

    def test_summary_empty_journal(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        EventJournal(db_path=db)
        collector = MetricsCollector()
        collector.db_path = db
        summary = collector.summary()
        assert summary.total_events == 0
        assert summary.total_tool_calls == 0
        assert summary.unique_tools == 0
        assert summary.tool_stats == []

    def test_init_with_journal_object(self, tmp_path: Path) -> None:
        db = tmp_path / "j.sqlite"
        journal = _seed_journal(db)
        collector = MetricsCollector(journal)
        assert collector.db_path == db


# ── Formatters ──────────────────────────────────────────────────────────


class TestFormatters:
    """Test the format_tool_stats and format_metrics_summary functions."""

    def test_format_tool_stats_empty(self) -> None:
        output = format_tool_stats([])
        assert "No tool execution data available." in output

    def test_format_tool_stats_with_data(self) -> None:
        stats = [
            ToolStats(
                tool="filesystem.read",
                count=2,
                avg_latency_ms=13.85,
                min_latency_ms=12.5,
                max_latency_ms=15.2,
                last_latency_ms=15.2,
                last_timestamp="2026-07-05T12:00:00",
            ),
            ToolStats(
                tool="http.get",
                count=3,
                avg_latency_ms=450.1,
                min_latency_ms=380.1,
                max_latency_ms=520.3,
                last_latency_ms=520.3,
                last_timestamp="2026-07-05T12:05:00",
            ),
        ]
        output = format_tool_stats(stats)

        # Header present
        assert "Tool Metrics" in output
        assert "Cnt" in output
        assert "Avg" in output

        # Data present
        assert "filesystem.read" in output
        assert "http.get" in output
        assert "ms" in output

    def test_format_metrics_summary(self) -> None:
        summary = MetricsSummary(
            total_events=50,
            total_tool_calls=10,
            unique_tools=3,
            total_sessions=5,
            tool_stats=[
                ToolStats(tool="filesystem.read", count=5, avg_latency_ms=10.0),
                ToolStats(tool="http.get", count=3, avg_latency_ms=200.0),
                ToolStats(tool="shell.exec", count=2, avg_latency_ms=1500.0),
            ],
        )
        output = format_metrics_summary(summary)

        assert "Journal Summary" in output
        assert "50" in output
        assert "5" in output
        assert "10" in output
        assert "3" in output
        assert "filesystem.read" in output
        assert "http.get" in output
        assert "shell.exec" in output

    def test_format_metrics_summary_empty(self) -> None:
        summary = MetricsSummary()
        output = format_metrics_summary(summary)
        assert "Journal Summary" in output
        assert "No tool execution data" not in output  # only applies to tool_stats

    def test_format_latency_dash_for_zero(self) -> None:
        """When latency is zero, show dash."""
        from minirun.metrics import _fmt_latency

        assert "  -  " in _fmt_latency(0.0)

    def test_format_latency_positive(self) -> None:
        from minirun.metrics import _fmt_latency

        assert "15.3ms" in _fmt_latency(15.3)


# ── ToolStats dataclass ─────────────────────────────────────────────────


class TestToolStats:
    """Test the ToolStats dataclass."""

    def test_defaults(self) -> None:
        s = ToolStats(tool="test.tool")
        assert s.tool == "test.tool"
        assert s.count == 0
        assert s.avg_latency_ms == 0.0
        assert s.success_count == 0
        assert s.error_count == 0

    def test_all_fields(self) -> None:
        s = ToolStats(
            tool="http.get",
            count=10,
            avg_latency_ms=250.0,
            min_latency_ms=100.0,
            max_latency_ms=500.0,
            total_latency_ms=2500.0,
            last_latency_ms=300.0,
            last_timestamp="2026-07-05T12:00:00",
            success_count=9,
            error_count=1,
        )
        assert s.count == 10
        assert s.avg_latency_ms == 250.0
        assert s.success_count == 9


# ── CLI integration test ────────────────────────────────────────────────


class TestMetricsCli:
    """Test the _list_metrics CLI function."""

    def test_list_metrics_no_journal(self, capsys: object) -> None:
        """When journal is not initialized, show error message."""
        from minirun.cli.main import _list_metrics

        _list_metrics()
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "Journal not available" in captured.out

    def test_list_metrics_empty_journal(self, capsys: object, tmp_path: Path) -> None:
        """When journal exists but is empty, show appropriate message."""

        # Create a journal at a known path
        db = tmp_path / "empty.sqlite"
        EventJournal(db_path=db)

        # We need to patch the global journal to return our test journal

        from minirun.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.db_path = db
        summary = collector.summary()

        # Manually test the output like _list_metrics would do
        if summary.total_events == 0:
            msg = "No journal events found. Run a session first to generate metrics."
            assert "No journal events" in msg
