"""Tests for summary retrieval behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from minirun.memory.summaries import KnowledgeIndex, search_summaries


class TestKnowledgeIndexRetrieval:
    def test_search_limit(self, tmp_path: Path):
        db = tmp_path / "index.sqlite"
        index = KnowledgeIndex(db_path=db)
        index.add(
            session_id="s1",
            prompt="datadog incident",
            created_at="2026-01-01T00:00:00Z",
        )
        index.add(
            session_id="s2",
            prompt="datadog monitor",
            created_at="2026-01-02T00:00:00Z",
        )
        index.add(
            session_id="s3",
            prompt="terraform plan",
            created_at="2026-01-03T00:00:00Z",
        )
        results = index.search("datadog", limit=2)
        assert len(results) == 2

    def test_search_no_match(self, tmp_path: Path):
        db = tmp_path / "index.sqlite"
        index = KnowledgeIndex(db_path=db)
        index.add(
            session_id="s1",
            prompt="datadog incident",
            created_at="2026-01-01T00:00:00Z",
        )
        results = index.search("kubernetes")
        assert results == []


class TestSearchSummariesEdgeCases:
    def test_search_returns_empty_on_storage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        db = tmp_path / "missing/index.sqlite"
        monkeypatch.setenv("MINIRUN_HOME", str(tmp_path))
        results = search_summaries("anything", db_path=db)
        assert results == []
