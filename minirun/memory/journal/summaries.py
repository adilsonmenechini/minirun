"""Session summaries: markdown session summaries + SQLite-backed retrieval.

Formerly ``memory/summaries.py`` — moved into the ``journal`` sub-package
for conceptual clarity (summaries are a type of journal entry, not memory).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from minirun.memory._db import use_rows


@dataclass
class Summary:
    session_id: str
    created_at: str
    prompt: str
    status: str
    path: Path | None = None
    error: str | None = None


class SessionIndex:
    """SQLite-backed index of session summaries.

    This was previously named ``KnowledgeIndex`` — renamed to avoid
    confusion with the ``knowledge`` store.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_summaries_session_id "
                "ON summaries(session_id)"
            )

    def add(self, session_id: str, prompt: str, created_at: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO summaries(session_id, prompt, created_at) VALUES(?,?,?)",
                (session_id, prompt, created_at),
            )

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            use_rows(conn)
            rows = conn.execute(
                "SELECT session_id, prompt, created_at "
                "FROM summaries WHERE prompt LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]


def summarize_session(
    session_id: str,
    prompt: str,
    messages: list[dict[str, Any]],
    provider: Any,
    summary_dir: Path | None = None,
    db_path: Path | None = None,
) -> Summary:
    summary_dir = summary_dir or _default_summary_dir()
    db_path = db_path or _default_db_path()
    path = summary_dir / f"{session_id}.md"
    created_at = datetime.now().isoformat()
    status = "ok"
    error = None

    try:
        response = provider(messages)
        content = (response.content or "").strip()
        if not content:
            content = "- No summary content returned"
    except Exception as exc:
        status = "error"
        content = f"- Summarization failed: {exc}"
        error = str(exc)

    summary_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Session {session_id}\n\n{content}\n", encoding="utf-8")

    try:
        index = SessionIndex(db_path=db_path)
        index.add(session_id=session_id, prompt=prompt, created_at=created_at)
    except Exception:
        status = "error" if status == "ok" else status

    return Summary(
        session_id=session_id,
        created_at=created_at,
        prompt=prompt,
        status=status,
        path=path,
        error=error,
    )


def search_session_summaries(
    query: str, limit: int = 3, db_path: Path | None = None
) -> list[dict[str, Any]]:
    """Search past session summaries by keyword.

    Renamed from ``search_summaries`` when moved into the journal package
    to make the scope explicit.
    """
    try:
        index = SessionIndex(db_path=db_path or _default_db_path())
        return index.search(query=query, limit=limit)
    except Exception:
        return []


def _default_summary_dir() -> Path:
    return Path("workspace/memory/sessions/summaries")


def _default_db_path() -> Path:
    return Path("workspace/memory/sessions/index.sqlite")
