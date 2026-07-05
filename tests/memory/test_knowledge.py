"""Tests for Knowledge Store: KnowledgeStore, KnowledgeExtractor, and helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from minirun.memory.extractor import KnowledgeExtractor
from minirun.memory.knowledge import (
    DuplicateFactError,
    KnowledgeFact,
    KnowledgeStore,
    compute_content_hash,
    normalize_content,
)

# ── Helpers ─────────────────────────────────────────────────────────────


class TestNormalizeContent:
    def test_lowercases(self) -> None:
        assert normalize_content("Hello World") == "hello world"

    def test_strips_whitespace(self) -> None:
        assert normalize_content("  hello  ") == "hello"

    def test_collapses_spaces(self) -> None:
        assert normalize_content("hello   world") == "hello world"

    def test_empty_string(self) -> None:
        assert normalize_content("") == ""

    def test_only_whitespace(self) -> None:
        assert normalize_content("   ") == ""


class TestComputeContentHash:
    def test_deterministic(self) -> None:
        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world")
        assert h1 == h2

    def test_different_inputs_differ(self) -> None:
        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world!")
        assert h1 != h2

    def test_normalized_equivalence(self) -> None:
        h1 = compute_content_hash(normalize_content("Hello  World"))
        h2 = compute_content_hash(normalize_content("hello world"))
        assert h1 == h2

    def test_sha256_length(self) -> None:
        h = compute_content_hash("test")
        assert len(h) == 64  # SHA-256 hex


# ── KnowledgeFact ───────────────────────────────────────────────────────


class TestKnowledgeFact:
    def test_new_creates_fact(self) -> None:
        fact = KnowledgeFact.new(
            content="incident-456 caused by database failover",
            source_session_id="session-abc",
            tags=["datadog"],
        )
        assert fact.id
        assert fact.content == "incident-456 caused by database failover"
        assert fact.source_session_id == "session-abc"
        assert "datadog" in fact.tags
        assert fact.confidence == 1.0
        assert fact.version == 1
        assert len(fact.content_hash) == 64
        assert fact.created_at == fact.updated_at

    def test_new_without_tags(self) -> None:
        fact = KnowledgeFact.new(content="test fact", source_session_id="s1")
        assert fact.tags == []

    def test_new_different_hashes_for_different_content(self) -> None:
        f1 = KnowledgeFact.new(content="fact one", source_session_id="s1")
        f2 = KnowledgeFact.new(content="fact two", source_session_id="s1")
        assert f1.content_hash != f2.content_hash

    def test_new_same_content_same_hash(self) -> None:
        f1 = KnowledgeFact.new(content="hello world", source_session_id="s1")
        f2 = KnowledgeFact.new(content="hello world", source_session_id="s2")
        assert f1.content_hash == f2.content_hash

    def test_new_with_ttl(self) -> None:
        """Fact created with ttl_days should have expires_at set."""
        fact = KnowledgeFact.new(
            content="test with ttl", source_session_id="s1", ttl_days=30
        )
        assert fact.expires_at is not None
        assert fact.expires_at > fact.created_at

    def test_new_without_ttl(self) -> None:
        """Fact created with ttl_days=0 should have no expiration."""
        fact = KnowledgeFact.new(
            content="no expiry", source_session_id="s1", ttl_days=0
        )
        assert fact.expires_at is None

    def test_new_default_ttl(self) -> None:
        """Default ttl_days is 90 — should set expires_at."""
        fact = KnowledgeFact.new(content="default ttl", source_session_id="s1")
        assert fact.expires_at is not None


# ── KnowledgeStore ──────────────────────────────────────────────────────


class TestKnowledgeStore:
    def test_init_creates_schema(self, tmp_path: Path) -> None:
        db = tmp_path / "knowledge.sqlite"
        KnowledgeStore(db_path=db)
        assert db.exists()
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='knowledge_facts'"
            ).fetchall()
        assert len(rows) == 1

    def test_add_and_retrieve(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        fact = KnowledgeFact.new(content="test fact", source_session_id="s1")
        store.add(fact)
        retrieved = store.get_by_id(fact.id)
        assert retrieved is not None
        assert retrieved.content == "test fact"
        assert retrieved.source_session_id == "s1"

    def test_add_duplicate_raises(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        fact = KnowledgeFact.new(content="test fact", source_session_id="s1")
        store.add(fact)
        same = KnowledgeFact.new(content="test fact", source_session_id="s2")
        with pytest.raises(DuplicateFactError):
            store.add(same)

    def test_upsert_new_creates(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        fact = KnowledgeFact.new(content="new fact", source_session_id="s1")
        stored = store.upsert(fact)
        assert stored.version == 1
        assert store.count() == 1

    def test_upsert_existing_updates(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        # Same content → same content_hash → triggers update path
        fact = KnowledgeFact.new(content="update me", source_session_id="s1")
        store.add(fact)

        updated = KnowledgeFact.new(
            content="update me",  # same content = same hash
            source_session_id="s2",
            tags=["updated"],
        )
        result = store.upsert(updated)
        assert result.version == 2  # incremented
        assert "updated" in result.tags
        assert store.count() == 1  # no duplicate

    def test_search_by_keyword(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        store.add(KnowledgeFact.new(content="database outage", source_session_id="s1"))
        store.add(KnowledgeFact.new(content="network latency", source_session_id="s1"))
        results = store.search("database")
        assert len(results) == 1
        assert "database" in results[0].content

    def test_search_with_tags(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        f1 = KnowledgeFact.new(
            content="incident-123", source_session_id="s1", tags=["datadog"]
        )
        f2 = KnowledgeFact.new(
            content="incident-456", source_session_id="s1", tags=["pagerduty"]
        )
        store.add(f1)
        store.add(f2)
        results = store.search("incident", tags=["datadog"])
        assert len(results) == 1
        assert "incident-123" in results[0].content

    def test_list_all_pagination(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        for i in range(5):
            store.add(KnowledgeFact.new(content=f"fact-{i}", source_session_id="s1"))
        all_facts = store.list_all(limit=3, offset=0)
        assert len(all_facts) == 3

    def test_get_by_id_nonexistent(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        assert store.get_by_id("nonexistent-uuid") is None

    def test_delete_existing(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        fact = KnowledgeFact.new(content="delete me", source_session_id="s1")
        store.add(fact)
        assert store.delete(fact.id) is True
        assert store.get_by_id(fact.id) is None

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        assert store.delete("nonexistent") is False

    def test_get_relevant(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        store.add(
            KnowledgeFact.new(
                content="database failover caused incident",
                source_session_id="s1",
                tags=["datadog"],
            )
        )
        store.add(
            KnowledgeFact.new(
                content="deploy completed successfully",
                source_session_id="s1",
                tags=["ci"],
            )
        )
        results = store.get_relevant("database", tags=["datadog"])
        assert len(results) == 1
        assert "database" in results[0].content

    def test_count(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite")
        assert store.count() == 0
        store.add(KnowledgeFact.new(content="a", source_session_id="s1"))
        store.add(KnowledgeFact.new(content="b", source_session_id="s1"))
        assert store.count() == 2

    def test_prune_removes_expired(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite", auto_prune=False)
        fact = KnowledgeFact.new(
            content="expired fact",
            source_session_id="s1",
            ttl_days=1,  # expires 1 day from now — NOT expired yet
        )
        store.add(fact)
        assert store.count() == 1

        # Manually set expires_at in the past
        import sqlite3

        with sqlite3.connect(store._db_path) as conn:
            conn.execute(
                "UPDATE knowledge_facts SET expires_at = '2020-01-01T00:00:00' "
                "WHERE id = ?",
                (fact.id,),
            )

        pruned = store.prune()
        assert pruned == 1
        assert store.count() == 0

    def test_prune_ignores_active(self, tmp_path: Path) -> None:
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite", auto_prune=False)
        store.add(
            KnowledgeFact.new(content="active fact", source_session_id="s1", ttl_days=0)
        )
        pruned = store.prune()
        assert pruned == 0
        assert store.count() == 1

    def test_auto_prune_on_init(self, tmp_path: Path) -> None:
        """Creating a new store should auto-prune expired facts."""
        store = KnowledgeStore(db_path=tmp_path / "k.sqlite", auto_prune=False)
        fact = KnowledgeFact.new(content="old", source_session_id="s1", ttl_days=1)
        store.add(fact)

        # Manually expire it
        import sqlite3

        with sqlite3.connect(store._db_path) as conn:
            conn.execute(
                "UPDATE knowledge_facts SET expires_at = '2020-01-01T00:00:00' "
                "WHERE id = ?",
                (fact.id,),
            )

        # New store with auto_prune=True should clean it
        store2 = KnowledgeStore(db_path=tmp_path / "k.sqlite", auto_prune=True)
        assert store2.count() == 0

    def test_default_db_path_creates_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that default db path creates parent directories."""
        monkeypatch.setattr(
            "minirun.memory.knowledge._default_db_path",
            lambda: tmp_path / "custom" / "k.sqlite",
        )
        store = KnowledgeStore()
        assert store._db_path.parent.exists()  # noqa: SLF001


# ── KnowledgeExtractor ─────────────────────────────────────────────────


class TestKnowledgeExtractor:
    def test_extract_incident(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="Check incident-456, caused by database failover",
            source_session_id="s1",
            tags=["datadog"],
        )
        assert len(result.facts) >= 1
        # At minimum the incident pattern should match
        incident_facts = [f for f in result.facts if "incident" in f.content.lower()]
        assert len(incident_facts) >= 1
        for f in result.facts:
            assert f.source_session_id == "s1"

    def test_extract_dependency(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="The api depends on the database service",
            source_session_id="s1",
        )
        dep_facts = [f for f in result.facts if "depends on" in f.content.lower()]
        assert len(dep_facts) >= 1

    def test_extract_root_cause(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="The outage was caused by a DNS misconfiguration",
            source_session_id="s1",
        )
        rc_facts = [f for f in result.facts if "caused by" in f.content.lower()]
        assert len(rc_facts) >= 1

    def test_extract_alert(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="The CPU threshold is 90% and triggered an alarm",
            source_session_id="s1",
        )
        alert_facts = [
            f
            for f in result.facts
            if "threshold" in f.content.lower() or "alarm" in f.content.lower()
        ]
        assert len(alert_facts) >= 1

    def test_extract_runbook(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="The runbook is at docs/deploy.md",
            source_session_id="s1",
        )
        rb_facts = [f for f in result.facts if "runbook" in f.content.lower()]
        assert len(rb_facts) >= 1

    def test_empty_content(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(content="", source_session_id="s1")
        assert len(result.facts) == 0
        assert result.skipped_count == 0

    def test_whitespace_content(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(content="   \n\n  ", source_session_id="s1")
        assert len(result.facts) == 0

    def test_short_content_skipped(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(content="hi", source_session_id="s1")
        assert len(result.facts) == 0

    def test_no_match(self) -> None:
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="This is a completely unrelated message about the weather.",
            source_session_id="s1",
        )
        assert len(result.facts) == 0

    def test_inline_dedup(self) -> None:
        """Same pattern match appearing twice should be deduplicated."""
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="incident-456 caused an issue. Check incident-456 for details.",
            source_session_id="s1",
        )
        # Only one fact for incident-456 should be created
        incident_facts = [f for f in result.facts if "incident-456" in f.content]
        assert len(incident_facts) <= 1

    def test_custom_patterns_direct(self) -> None:
        import re

        custom = {"custom_endpoint": re.compile(r"endpoint[:=]\s*(\S+)", re.IGNORECASE)}
        extractor = KnowledgeExtractor(patterns=custom)
        result = extractor.extract(
            content="Check endpoint: /api/health",
            source_session_id="s1",
            tags=["custom"],
        )
        assert len(result.facts) == 1
        assert "/api/health" in result.facts[0].content

    # ── YAML config loading ────────────────────────────────────────

    def test_load_from_yaml_custom_pattern(self, tmp_path: Path) -> None:
        """Custom pattern from YAML is loaded and matches."""
        config = tmp_path / "knowledge.yaml"
        config.write_text("patterns:\n  deploy_fail: 'deploy(ment)? failed'\n")
        extractor = KnowledgeExtractor(config_path=config)
        result = extractor.extract(
            content="The deployment failed due to a timeout",
            source_session_id="s1",
        )
        deploy_facts = [f for f in result.facts if "deploy" in f.content.lower()]
        assert len(deploy_facts) >= 1
        # Default patterns still work alongside custom ones
        assert len(result.facts) >= 1

    def test_load_from_yaml_overrides_default(self, tmp_path: Path) -> None:
        """Custom pattern with same name as a default overrides it."""
        config = tmp_path / "knowledge.yaml"
        config.write_text('patterns:\n  incident: "MY_CUSTOM_INCIDENT"\n')
        extractor = KnowledgeExtractor(config_path=config)
        # The custom incident pattern should NOT match "incident-456"
        result = extractor.extract(
            content="Check incident-456 please",
            source_session_id="s1",
        )
        assert len(result.facts) == 0

    def test_load_from_yaml_invalid_regex_skipped(self, tmp_path: Path) -> None:
        """Invalid regex in YAML is silently skipped; defaults remain."""
        config = tmp_path / "knowledge.yaml"
        # Use a pattern that produces a match longer than _MIN_CONTENT_LENGTH (10)
        config.write_text(
            'patterns:\n  bad: "[invalid"\n'
            '  long_match: "database failover was handled"\n'
        )
        extractor = KnowledgeExtractor(config_path=config)
        result = extractor.extract(
            content="The database failover was handled by the team",
            source_session_id="s1",
        )
        # "long_match" pattern should produce at least one fact
        assert len(result.facts) >= 1
        # Default patterns still work (e.g. runbook didn't get overridden)
        # "The" is only 3 chars — won't match. Check that default incident still works
        result2 = extractor.extract(
            content="Check incident-456",
            source_session_id="s1",
        )
        assert len(result2.facts) >= 1

    def test_load_from_yaml_missing_file_uses_defaults(self) -> None:
        """Non-existent YAML file falls back to default patterns."""
        extractor = KnowledgeExtractor(
            config_path=Path("/tmp/nonexistent_knowledge.yaml")
        )
        result = extractor.extract(
            content="Check incident-456",
            source_session_id="s1",
        )
        assert len(result.facts) >= 1

    def test_load_from_yaml_empty_uses_defaults(self, tmp_path: Path) -> None:
        """Empty YAML file falls back to default patterns."""
        config = tmp_path / "empty.yaml"
        config.write_text("")
        extractor = KnowledgeExtractor(config_path=config)
        result = extractor.extract(
            content="Check incident-456",
            source_session_id="s1",
        )
        assert len(result.facts) >= 1

    def test_default_extractor_uses_yaml_if_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KnowledgeExtractor() (no args) loads from config/knowledge.yaml."""
        custom_config = tmp_path / "knowledge.yaml"
        # Use single quotes in YAML to avoid Python re patterns with backslashes
        custom_config.write_text("patterns:\n  health_check: 'endpoint status'\n")
        monkeypatch.setattr(
            "minirun.memory.extractor.KNOWLEDGE_CONFIG_PATH",
            custom_config,
        )
        extractor = KnowledgeExtractor()
        result = extractor.extract(
            content="Check api.health endpoint status",
            source_session_id="s1",
        )
        assert len(result.facts) >= 1
