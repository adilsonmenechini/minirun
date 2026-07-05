"""Knowledge store: SQLite-backed persistence for extracted facts."""

import hashlib
import json
import re
import sqlite3
import uuid as uuid_mod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from minirun.memory._db import use_rows

# ── Exceptions ──────────────────────────────────────────────────────────


class DuplicateFactError(ValueError):
    """Raised when KnowledgeStore.add() encounters an existing content_hash."""

    def __init__(self, content_hash: str) -> None:
        self.content_hash = content_hash
        super().__init__(f"Fact with content_hash '{content_hash}' already exists")


# ── Dataclasses ─────────────────────────────────────────────────────────


@dataclass
class KnowledgeFact:
    """A single structured fact extracted from an LLM response."""

    id: str
    content: str
    source_session_id: str
    created_at: str
    updated_at: str
    tags: list[str]
    content_hash: str = ""
    confidence: float = 1.0
    version: int = 1
    expires_at: str | None = None

    def __post_init__(self) -> None:
        if not hasattr(self, "tags"):
            self.tags = []

    @staticmethod
    def new(
        content: str,
        source_session_id: str,
        tags: list[str] | None = None,
        confidence: float = 1.0,
        ttl_days: int = 90,
    ) -> "KnowledgeFact":
        """Create a new KnowledgeFact with auto-generated id, hash, and timestamps.

        Args:
            content: The fact text.
            source_session_id: UUID of the source session.
            tags: Optional categorization tags.
            confidence: Extraction confidence (0.0-1.0).
            ttl_days: Time-to-live in days. Fact expires after this many days
                      from creation. Set to 0 for no expiration.
        """
        now = datetime.now(UTC)
        expires_at: str | None = None
        if ttl_days > 0:
            expires = now + timedelta(days=ttl_days)
            expires_at = expires.isoformat()

        normalized = normalize_content(content)
        return KnowledgeFact(
            id=str(uuid_mod.uuid4()),
            content=content,
            source_session_id=source_session_id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            tags=tags or [],
            content_hash=compute_content_hash(normalized),
            confidence=confidence,
            version=1,
            expires_at=expires_at,
        )


@dataclass
class ExtractionResult:
    """Result from a single extraction pass over an LLM response."""

    facts: list[KnowledgeFact]
    skipped_count: int = 0

    def __post_init__(self) -> None:
        if not hasattr(self, "facts"):
            self.facts = []


# ── Helpers ─────────────────────────────────────────────────────────────


def normalize_content(content: str) -> str:
    """Normalize content for consistent hashing.

    - Lowercase
    - Strip leading/trailing whitespace
    - Collapse multiple spaces into one
    """
    return re.sub(r"\s+", " ", content.strip().lower())


def compute_content_hash(normalized: str) -> str:
    """Compute a SHA-256 hex digest of normalized content."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ── Default paths ──────────────────────────────────────────────────────


def _default_db_dir() -> Path:
    return Path("workspace/memory/knowledge")


def _default_db_path() -> Path:
    return _default_db_dir() / "index.sqlite"


# ── KnowledgeStore ─────────────────────────────────────────────────────


class KnowledgeStore:
    """SQLite-backed persistence layer for KnowledgeFacts."""

    def __init__(self, db_path: Path | None = None, auto_prune: bool = True) -> None:
        self._db_path = db_path or _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        if auto_prune:
            pruned = self.prune()
            if pruned:
                import logging

                logging.getLogger("runtime").info(
                    "Pruned %d expired knowledge fact(s)", pruned
                )

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_facts (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    content_hash TEXT NOT NULL UNIQUE,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    version INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_content_hash "
                "ON knowledge_facts(content_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge_facts(tags)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_created_at "
                "ON knowledge_facts(created_at DESC)"
            )
            # Migration: add expires_at column if missing (safe on existing DBs)
            try:
                conn.execute("ALTER TABLE knowledge_facts ADD COLUMN expires_at TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

    def _row_to_fact(self, row: sqlite3.Row) -> KnowledgeFact:
        return KnowledgeFact(
            id=row["id"],
            content=row["content"],
            source_session_id=row["source_session_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=json.loads(row["tags"]),
            content_hash=row["content_hash"],
            confidence=row["confidence"],
            version=row["version"],
            expires_at=row["expires_at"],
        )

    # ── CRUD ───────────────────────────────────────────────────────────

    def add(self, fact: KnowledgeFact) -> None:
        """Insert a new fact. Raises DuplicateFactError if content_hash exists."""
        with sqlite3.connect(self._db_path) as conn:
            try:
                conn.execute(
                    """INSERT INTO knowledge_facts
                       (id, content, source_session_id, created_at, updated_at,
                        tags, content_hash, confidence, version, expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fact.id,
                        fact.content,
                        fact.source_session_id,
                        fact.created_at,
                        fact.updated_at,
                        json.dumps(fact.tags),
                        fact.content_hash,
                        fact.confidence,
                        fact.version,
                        fact.expires_at,
                    ),
                )
            except sqlite3.IntegrityError:
                raise DuplicateFactError(fact.content_hash) from None

    def upsert(self, fact: KnowledgeFact) -> KnowledgeFact:
        """Insert or update. If content_hash exists, increment version.

        Returns the stored (possibly updated) fact.
        """
        with sqlite3.connect(self._db_path) as conn:
            use_rows(conn)
            existing = conn.execute(
                "SELECT * FROM knowledge_facts WHERE content_hash = ?",
                (fact.content_hash,),
            ).fetchone()

        if existing is None:
            self.add(fact)
            return fact

        # Update existing fact
        old = self._row_to_fact(existing)
        now = datetime.now(UTC).isoformat()
        updated = KnowledgeFact(
            id=old.id,
            content=fact.content,
            source_session_id=fact.source_session_id,
            created_at=old.created_at,
            updated_at=now,
            tags=fact.tags or old.tags,
            content_hash=old.content_hash,
            confidence=fact.confidence,
            version=old.version + 1,
            expires_at=old.expires_at,
        )
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """UPDATE knowledge_facts SET
                       content=?, source_session_id=?, updated_at=?, tags=?,
                       confidence=?, version=?, expires_at=?
                   WHERE content_hash = ?""",
                (
                    updated.content,
                    updated.source_session_id,
                    updated.updated_at,
                    json.dumps(updated.tags),
                    updated.confidence,
                    updated.version,
                    updated.expires_at,
                    updated.content_hash,
                ),
            )
        return updated

    def search(
        self,
        query: str,
        limit: int = 10,
        tags: list[str] | None = None,
    ) -> list[KnowledgeFact]:
        """Keyword search across content field with optional tag filter.

        Tags are stored as JSON arrays (e.g. '["datadog"]'). Filtering
        uses LIKE with JSON-escaped values to match array membership.
        """
        with sqlite3.connect(self._db_path) as conn:
            use_rows(conn)
            if tags:
                tag_conditions = " AND ".join("tags LIKE ?" for _ in tags)
                tag_params = [f'%"{t}"%' for t in tags]
                rows = conn.execute(
                    f"""SELECT * FROM knowledge_facts
                        WHERE content LIKE ?
                          AND {tag_conditions}
                        ORDER BY created_at DESC
                        LIMIT ?""",
                    [f"%{query}%"] + tag_params + [limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM knowledge_facts
                       WHERE content LIKE ?
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (f"%{query}%", limit),
                ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def list_all(self, limit: int = 50, offset: int = 0) -> list[KnowledgeFact]:
        """Paginated listing ordered by created_at descending."""
        with sqlite3.connect(self._db_path) as conn:
            use_rows(conn)
            rows = conn.execute(
                "SELECT * FROM knowledge_facts "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def get_by_id(self, fact_id: str) -> KnowledgeFact | None:
        """Retrieve a single fact by UUID."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM knowledge_facts WHERE id = ?", (fact_id,)
            ).fetchone()
        return self._row_to_fact(row) if row else None

    def delete(self, fact_id: str) -> bool:
        """Delete a fact by UUID. Returns True if deleted, False if not found."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM knowledge_facts WHERE id = ?", (fact_id,)
            )
            return cursor.rowcount > 0

    def get_relevant(
        self,
        query: str,
        tags: list[str] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeFact]:
        """Retrieve facts relevant to a prompt/profile for context injection."""
        return self.search(query=query, tags=tags, limit=limit)

    def count(self) -> int:
        """Return total number of facts in the store (including expired)."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_facts").fetchone()
            return row[0] if row else 0

    def prune(self) -> int:
        """Delete all expired facts.

        A fact is expired if expires_at is not NULL and expires_at < now.

        Returns:
            Number of facts deleted.
        """
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM knowledge_facts "
                "WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            return cursor.rowcount
