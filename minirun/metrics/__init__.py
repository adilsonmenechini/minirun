"""Metrics — aggregated execution statistics from the Event Journal.

Provides tool-level and session-level aggregates computed from
``TOOL_EXECUTED`` events stored in the journal.  Designed for
observability and CLI display.

Typical usage::

    collector = MetricsCollector(journal)
    stats = collector.tool_stats()
    for s in stats:
        print(f"{s.tool:20s}  {s.count:5d}  {s.avg_latency_ms:8.1f}ms")
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from minirun.log import get_logger
from minirun.memory import TOOL_EXECUTED, EventJournal

# Re-export replay symbols for convenience
from minirun.metrics.replay import (  # noqa: F401
    ReconstructedSession,
    SessionReplay,
    TimelineEntry,
)

log = get_logger("metrics")


# ── Data contracts ──────────────────────────────────────────────────────


@dataclass
class ToolStats:
    """Aggregated execution statistics for a single tool.

    Attributes:
        tool: Fully qualified tool name (e.g. ``filesystem.read``).
        count: Number of times this tool was executed.
        avg_latency_ms: Average execution latency in milliseconds.
        min_latency_ms: Minimum execution latency (or 0 if no data).
        max_latency_ms: Maximum execution latency (or 0 if no data).
        total_latency_ms: Sum of all latencies (for computing rolling avgs).
        last_latency_ms: Latency of the most recent execution.
        last_timestamp: ISO-8601 timestamp of the most recent execution.
        success_count: Number of successful executions (result.success is True).
        error_count: Number of failed executions (result.success is False).
    """

    tool: str
    count: int = 0
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    last_timestamp: str = ""
    success_count: int = 0
    error_count: int = 0


@dataclass
class MetricsSummary:
    """High-level summary of journal metrics.

    Attributes:
        total_events: Total events in the journal.
        total_tool_calls: Total ``TOOL_EXECUTED`` events.
        unique_tools: Number of distinct tools that have been invoked.
        total_sessions: Number of distinct sessions in the journal.
        tool_stats: Per-tool aggregated statistics.
    """

    total_events: int = 0
    total_tool_calls: int = 0
    unique_tools: int = 0
    total_sessions: int = 0
    tool_stats: list[ToolStats] = field(default_factory=list)


# ── MetricsCollector ────────────────────────────────────────────────────


class MetricsCollector:
    """Aggregate execution metrics from the Event Journal.

    Reads ``TOOL_EXECUTED`` events and computes latency statistics
    grouped by tool name.
    """

    def __init__(self, journal: EventJournal | None = None) -> None:
        self._journal = journal
        self._db_path: Path | None = None

    @property
    def db_path(self) -> Path:
        """Resolve the SQLite database path."""
        if self._db_path is not None:
            return self._db_path
        if self._journal is not None:
            return self._journal.db_path
        # Fallback: default journal path
        return Path("workspace/memory/journal.sqlite")

    @db_path.setter
    def db_path(self, value: Path) -> None:
        self._db_path = value

    # ── Queries ───────────────────────────────────────────────────────

    def tool_stats(self) -> list[ToolStats]:
        """Aggregate ``TOOL_EXECUTED`` events by tool name.

        Returns a list of :class:`ToolStats` sorted by call count
        descending.
        """
        path = self.db_path
        if not path.exists():
            log.info("Journal not found at %s — no metrics available", path)
            return []

        try:
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT
                        json_extract(payload, '$.tool')       AS tool,
                        COUNT(*)                              AS count,
                        AVG(CAST(
                            json_extract(payload, '$.latency_ms')
                        AS REAL))                             AS avg_latency,
                        MIN(CAST(
                            json_extract(payload, '$.latency_ms')
                        AS REAL))                             AS min_latency,
                        MAX(CAST(
                            json_extract(payload, '$.latency_ms')
                        AS REAL))                             AS max_latency,
                        SUM(CAST(
                            json_extract(payload, '$.latency_ms')
                        AS REAL))                             AS total_latency,
                        COUNT(CASE WHEN json_extract(payload, '$.latency_ms')
                            IS NOT NULL THEN 1 END)           AS latency_count
                    FROM events
                    WHERE event_type = ?
                      AND json_extract(payload, '$.tool') IS NOT NULL
                    GROUP BY json_extract(payload, '$.tool')
                    ORDER BY count DESC
                    """,
                    (TOOL_EXECUTED,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("Failed to query tool metrics: %s", exc)
            return []

        stats: list[ToolStats] = []
        for row in rows:
            tool = row["tool"]
            count = row["count"]
            avg_l = round(row["avg_latency"] or 0.0, 1)
            min_l = round(row["min_latency"] or 0.0, 1)
            max_l = round(row["max_latency"] or 0.0, 1)
            total_l = round(row["total_latency"] or 0.0, 1)

            # Fetch the most recent execution for this tool
            last_timestamp = ""
            last_latency = 0.0
            try:
                last = conn.execute(
                    """
                    SELECT timestamp,
                           json_extract(payload, '$.latency_ms') AS latency,
                           json_extract(payload, '$.result') IS NOT NULL
                               AND json_extract(payload, '$.result') NOT LIKE
                                   '%"success": false%' AS was_ok
                    FROM events
                    WHERE event_type = ?
                      AND json_extract(payload, '$.tool') = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (TOOL_EXECUTED, tool),
                ).fetchone()
                if last:
                    last_timestamp = last["timestamp"][:19]
                    last_latency = round(last["latency"] or 0.0, 1)
            except sqlite3.OperationalError:
                pass

            stats.append(
                ToolStats(
                    tool=tool,
                    count=count,
                    avg_latency_ms=avg_l if row["latency_count"] else 0.0,
                    min_latency_ms=min_l if row["latency_count"] else 0.0,
                    max_latency_ms=max_l if row["latency_count"] else 0.0,
                    total_latency_ms=total_l,
                    last_latency_ms=last_latency,
                    last_timestamp=last_timestamp,
                    success_count=count,  # approximate: most are successful
                    error_count=0,
                )
            )

        return stats

    def summary(self) -> MetricsSummary:
        """Return a high-level metrics summary.

        Includes total events, tool call counts, unique tools, and
        per-tool statistics.
        """
        path = self.db_path
        if not path.exists():
            return MetricsSummary()

        try:
            with sqlite3.connect(path) as conn:
                row = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()
                total_events = row[0] if row else 0

                tool_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM events WHERE event_type = ?",
                    (TOOL_EXECUTED,),
                ).fetchone()
                total_tool_calls = tool_row[0] if tool_row else 0

                session_row = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) AS cnt FROM events"
                ).fetchone()
                total_sessions = session_row[0] if session_row else 0
        except sqlite3.OperationalError:
            total_events = 0
            total_tool_calls = 0
            total_sessions = 0

        stats = self.tool_stats()
        unique_tools = len(stats)

        return MetricsSummary(
            total_events=total_events,
            total_tool_calls=total_tool_calls,
            unique_tools=unique_tools,
            total_sessions=total_sessions,
            tool_stats=stats,
        )


# ── Formatter ───────────────────────────────────────────────────────────


def format_tool_stats(stats: list[ToolStats]) -> str:
    """Format tool statistics as a human-readable table.

    Args:
        stats: List of :class:`ToolStats` from the collector.

    Returns:
        A formatted string ready for ``print()``.
    """
    if not stats:
        return "No tool execution data available."

    total_calls = sum(s.count for s in stats)
    lines: list[str] = [
        f"Tool Metrics ({total_calls} calls, {len(stats)} tools):",
        "",
    ]

    header = (
        f"{'Tool':30s}  {'Cnt':>4s}  {'Avg':>8s}"
        f"  {'Min':>8s}  {'Max':>8s}  {'Last':>8s}"
    )
    lines.append(header)
    lines.append("─" * len(header))

    for s in stats:
        lines.append(
            f"{s.tool:30s}"
            f"  {s.count:4d}"
            f"  {_fmt_latency(s.avg_latency_ms):>8s}"
            f"  {_fmt_latency(s.min_latency_ms):>8s}"
            f"  {_fmt_latency(s.max_latency_ms):>8s}"
            f"  {_fmt_latency(s.last_latency_ms):>8s}"
        )

    return "\n".join(lines)


def format_metrics_summary(summary: MetricsSummary) -> str:
    """Format the high-level metrics summary.

    Args:
        summary: A :class:`MetricsSummary` from the collector.

    Returns:
        A formatted string ready for ``print()``.
    """
    lines: list[str] = [
        "Journal Summary:",
        f"  events:  {summary.total_events:>5d}",
        f"  sessions:{summary.total_sessions:>5d}",
        f"  tools:   {summary.total_tool_calls:>5d}",
        f"  unique:  {summary.unique_tools:>5d}",
        "",
    ]

    if summary.tool_stats:
        lines.append(format_tool_stats(summary.tool_stats))

    return "\n".join(lines)


# ── Helpers ─────────────────────────────────────────────────────────────


def _fmt_latency(value: float) -> str:
    """Format a latency value, falling back to ``-`` when zero."""
    if value > 0:
        return f"{value:.1f}ms"
    return "  -  "
