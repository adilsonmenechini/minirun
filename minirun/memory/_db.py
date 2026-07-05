"""Shared SQLite helpers to avoid row_factory duplication across modules."""

from __future__ import annotations

import sqlite3


def use_rows(conn: sqlite3.Connection) -> None:
    """Set row_factory on a SQLite connection for dict-like row access."""
    conn.row_factory = sqlite3.Row
