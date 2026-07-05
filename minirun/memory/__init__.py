"""Memory module: persistence, summaries, and knowledge."""

from minirun.memory.extractor import ExtractionResult, KnowledgeExtractor
from minirun.memory.knowledge import (
    DuplicateFactError,
    KnowledgeFact,
    KnowledgeStore,
    compute_content_hash,
    normalize_content,
)
from minirun.memory.summaries import (
    KnowledgeIndex,
    Summary,
    search_summaries,
    summarize_session,
)

__all__ = [
    "Summary",
    "KnowledgeIndex",
    "summarize_session",
    "search_summaries",
    "KnowledgeFact",
    "KnowledgeStore",
    "DuplicateFactError",
    "KnowledgeExtractor",
    "ExtractionResult",
    "normalize_content",
    "compute_content_hash",
]
