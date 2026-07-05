"""Knowledge Builder — post-session knowledge extraction and persistence.

After a session ends, this module extracts structured facts from the full
conversation (user messages + assistant responses) and persists them to
the :class:`~minirun.memory.knowledge.KnowledgeStore` for future context
injection.
"""

from __future__ import annotations

from typing import Any

from minirun.log import get_logger
from minirun.memory.extractor import KnowledgeExtractor
from minirun.memory.knowledge import KnowledgeStore

log = get_logger("runtime.knowledge")


def build_knowledge(
    messages: list[dict[str, str]] | list[Any],
    source_session_id: str,
    tags: list[str] | None = None,
    store: KnowledgeStore | None = None,
    extractor: KnowledgeExtractor | None = None,
) -> dict[str, int]:
    """Extract and persist knowledge facts from a full conversation.

    Processes every message in the conversation (both user and assistant)
    through the :class:`~minirun.memory.extractor.KnowledgeExtractor`,
    then upserts each extracted fact into the
    :class:`~minirun.memory.knowledge.KnowledgeStore`.

    Args:
        messages: Conversation messages.  Each item must have ``role``
            and ``content`` attributes (either as dict keys or object
            attributes).
        source_session_id: UUID of the session being finalised.
        tags: Optional tags applied to every extracted fact (e.g. the
            active profile name).
        store: A :class:`KnowledgeStore` instance.  If ``None``, a fresh
            one is created (with auto-prune).
        extractor: A :class:`KnowledgeExtractor` instance.  If ``None``,
            a default one is created (uses built-in patterns + optional
            ``config/knowledge.yaml``).

    Returns:
        A dict with keys ``extracted`` (number of facts persisted) and
        ``skipped`` (number of matches skipped for being too short or
        duplicates within the same response).
    """
    store = store or KnowledgeStore()
    extractor = extractor or KnowledgeExtractor()

    total_extracted = 0
    total_skipped = 0

    for msg in messages:
        # Normalise message access — supports both dicts and objects
        if isinstance(msg, dict):
            content: str | None = msg.get("content", "")
        else:
            content = getattr(msg, "content", None)

        if not content or not content.strip():
            continue

        result = extractor.extract(
            content=content,
            source_session_id=source_session_id,
            tags=tags,
        )

        for fact in result.facts:
            store.upsert(fact)

        total_extracted += len(result.facts)
        total_skipped += result.skipped_count

    if total_extracted:
        log.info(
            "Knowledge build complete: %d fact(s) extracted, %d skipped",
            total_extracted,
            total_skipped,
        )
    else:
        log.debug("Knowledge build: no facts extracted (%d skipped)", total_skipped)

    return {"extracted": total_extracted, "skipped": total_skipped}
