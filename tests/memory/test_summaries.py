"""Tests for memory summarization and retrieval."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from minirun.memory.journal import (
    SessionIndex,
    Summary,
    search_session_summaries,
    summarize_session,
)


class TestSummaryDataclass:
    def test_defaults(self):
        summary = Summary(
            session_id="abc",
            created_at="2026-01-01T00:00:00Z",
            prompt="p",
            status="ok",
        )
        assert summary.session_id == "abc"
        assert summary.status == "ok"
        assert summary.path is None


class TestSessionIndex:
    def test_init_creates_schema(self, tmp_path: Path):
        db = tmp_path / "index.sqlite"
        SessionIndex(db_path=db)
        assert db.exists()
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='summaries'"
            ).fetchall()
        assert len(rows) == 1

    def test_add_and_search(self, tmp_path: Path):
        db = tmp_path / "index.sqlite"
        index = SessionIndex(db_path=db)
        index.add(
            session_id="s1",
            prompt="datadog incident",
            created_at="2026-01-01T00:00:00Z",
        )
        results = index.search("datadog")
        assert len(results) == 1
        assert results[0]["session_id"] == "s1"


class TestSummarizeSession:
    def test_success_writes_markdown_and_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        session_id = str(uuid4())
        summary_dir = tmp_path / "summaries"
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))

        def fake_provider(  # pragma: no cover - simple fake
            messages: list[dict[str, Any]],
        ) -> Any:
            class FakeResponse:
                content = "- reviewed incident\n- fixed deploy"

            return FakeResponse()

        summary = summarize_session(
            session_id=session_id,
            prompt="incident 123",
            messages=[{"role": "user", "content": "incident 123"}],
            provider=fake_provider,
            summary_dir=summary_dir,
            db_path=tmp_path / "index.sqlite",
        )
        assert summary.status == "ok"
        expected_file = summary_dir / f"{session_id}.md"
        assert expected_file.exists()
        assert "reviewed incident" in expected_file.read_text(encoding="utf-8")

    def test_failure_writes_stub(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        session_id = str(uuid4())
        summary_dir = tmp_path / "summaries"
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))

        def failing_provider(  # pragma: no cover - simple fake
            messages: list[dict[str, Any]],
        ) -> Any:
            raise RuntimeError("provider down")

        summary = summarize_session(
            session_id=session_id,
            prompt="incident 123",
            messages=[{"role": "user", "content": "incident 123"}],
            provider=failing_provider,
            summary_dir=summary_dir,
            db_path=tmp_path / "index.sqlite",
        )
        assert summary.status == "error"
        expected_file = summary_dir / f"{session_id}.md"
        assert expected_file.exists()
        assert "provider down" in expected_file.read_text(encoding="utf-8")


class TestSearchSessionSummaries:
    def test_search_returns_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        db = tmp_path / "index.sqlite"
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))
        index = SessionIndex(db_path=db)
        index.add(
            session_id="s1",
            prompt="datadog incident",
            created_at="2026-01-01T00:00:00Z",
        )
        results = search_session_summaries("datadog", db_path=db)
        assert len(results) == 1

    def test_search_empty_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        db = tmp_path / "index.sqlite"
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))
        SessionIndex(db_path=db)
        results = search_session_summaries("datadog", db_path=db)
        assert results == []
