"""Memory context builder — past session summaries and knowledge facts.

Extracted from :mod:`minirun.runtime.harness` to keep the harness focused
on orchestration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from minirun.log import get_logger
from minirun.memory.journal import search_session_summaries
from minirun.workspace import Workspace

log = get_logger("runtime.context")


# ── Helpers ─────────────────────────────────────────────────────────────


def _get_default_db_path() -> Path:
    """Return the default SQLite path for the memory index."""
    ws = Workspace()
    return ws.root / "memory" / "sessions" / "index.sqlite"


def _get_default_summary_dir() -> Path:
    """Return the default directory for session summary files."""
    ws = Workspace()
    return ws.root / "memory" / "sessions" / "summaries"


# ── Context builder ─────────────────────────────────────────────────────


def build_memory_context(
    prompt: str,
    db_path: Path | None = None,
    max_summaries: int = 2,
    knowledge_store: Any | None = None,
    profile_name: str | None = None,
    max_knowledge_facts: int = 5,
) -> str | None:
    """Build a memory context string from relevant past session summaries and knowledge.

    Queries :func:`search_session_summaries` for summaries matching the
    current prompt, and optionally queries a ``KnowledgeStore`` for
    relevant facts.  Returns ``None`` when no relevant context is found.

    Args:
        prompt: The current user prompt to match against past summaries.
        db_path: Override SQLite path (optional).
        max_summaries: Maximum number of past summaries to include.
        knowledge_store: Optional KnowledgeStore instance for fact retrieval.
        profile_name: Profile name for tag-based fact filtering.
        max_knowledge_facts: Maximum number of knowledge facts to include.

    Returns:
        Formatted context string, or ``None`` if no matches.
    """
    lines: list[str] = []
    has_context = False

    # Session summaries section
    try:
        results = search_session_summaries(
            query=prompt, limit=max_summaries, db_path=db_path
        )
    except Exception:
        log.warning("Failed to search past summaries", exc_info=True)
        results = []

    if results:
        has_context = True
        lines.append("### Past sessions:")
        for r in results:
            sid = r.get("session_id", "?")[:8]
            pr = r.get("prompt", "?")
            lines.append(f"- {pr} [{sid}]")

    # Knowledge facts section
    if knowledge_store is not None:
        try:
            tags = [profile_name] if profile_name else None
            facts = knowledge_store.get_relevant(
                query=prompt, tags=tags, limit=max_knowledge_facts
            )
        except Exception:
            log.warning("Failed to query knowledge store", exc_info=True)
            facts = []

        if facts:
            has_context = True
            if results:
                lines.append("")
            lines.append("## Knowledge")
            for f in facts:
                preview = f.content[:60]
                tag = f.tags[0] if f.tags else "?"
                lines.append(f"- {preview} [{tag}]")

    if not has_context:
        return None

    return "\n".join(lines)
