"""Knowledge extractor: pattern-based fact extraction from LLM responses."""

from __future__ import annotations

import re
from pathlib import Path
from re import Pattern
from typing import Any

from minirun.memory.knowledge import ExtractionResult, KnowledgeFact

# ── Default pattern registry ────────────────────────────────────────────

DEFAULT_PATTERNS: dict[str, Pattern[str]] = {
    "incident": re.compile(r"(incident|case|ticket)[-#:\s]*(\w+)", re.IGNORECASE),
    "dependency": re.compile(
        r"(\w+)\s+(depends on|requires|uses)\s+(\w+)", re.IGNORECASE
    ),
    "root_cause": re.compile(r"(caused by|due to|triggered by)\s+(.+)", re.IGNORECASE),
    "alert": re.compile(
        r"(alert|alarm|threshold)\s*(:|=|is|was)\s*(.+)", re.IGNORECASE
    ),
    "runbook": re.compile(r"(runbook|doc|docs?)\s*(:|=|is|at)\s*(.+)", re.IGNORECASE),
}


_MIN_CONTENT_LENGTH = 10

# ── Config path ─────────────────────────────────────────────────────────


KNOWLEDGE_CONFIG_PATH = Path("config/knowledge.yaml")


# ── YAML loader ─────────────────────────────────────────────────────────


def _load_yaml_safe(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file, returning {} on any error."""
    try:
        import yaml
    except ImportError:
        return {}

    if not path.is_file():
        return {}

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (yaml.YAMLError, OSError):
        return {}


# ── Pattern loader ──────────────────────────────────────────────────────


def load_knowledge_patterns(
    config_path: Path | None = None,
) -> dict[str, Pattern[str]]:
    """Load patterns from YAML config, merged with defaults.

    The YAML file should have a top-level key ``patterns`` whose value is
    a mapping of pattern names to regex strings.  Each regex is compiled
    with ``re.IGNORECASE``.  Custom patterns are **merged** with
    ``DEFAULT_PATTERNS`` — a custom pattern with the same name as a
    built-in one will **override** it.

    If the file is missing, empty, or invalid, only the defaults are
    returned (no error is raised).
    """
    data = _load_yaml_safe(config_path or KNOWLEDGE_CONFIG_PATH)
    raw_patterns: dict[str, str] | None = data.get("patterns") if data else None

    if not raw_patterns:
        return dict(DEFAULT_PATTERNS)

    merged: dict[str, Pattern[str]] = {}

    # Start with defaults
    for name, pat in DEFAULT_PATTERNS.items():
        merged[name] = pat

    # Apply custom patterns (overrides built-ins with same name)
    for name, regex_str in raw_patterns.items():
        try:
            compiled = re.compile(regex_str, re.IGNORECASE)
            merged[name] = compiled
        except re.error:
            continue  # skip invalid regex, keep existing default if any

    return merged


class KnowledgeExtractor:
    """Analyzes LLM response content and extracts structured facts.

    Uses regex patterns (v1) with a configurable pattern registry.
    Extraction is heuristic-based — no separate LLM call is made.

    Args:
        config_path: Path to a YAML file with custom patterns. If None,
                     ``config/knowledge.yaml`` is used. Patterns from the
                     YAML are merged with ``DEFAULT_PATTERNS``.
        patterns: Direct pattern override. If provided, ``config_path``
                  is ignored and ``patterns`` is used as-is. This takes
                  precedence over ``config_path``.
    """

    def __init__(
        self,
        config_path: Path | None = None,
        patterns: dict[str, Pattern[str]] | None = None,
    ) -> None:
        if patterns is not None:
            self.patterns = patterns
        else:
            self.patterns = load_knowledge_patterns(config_path)

    def extract(
        self,
        content: str,
        source_session_id: str,
        tags: list[str] | None = None,
    ) -> ExtractionResult:
        """Run patterns against content and return extracted facts.

        - Empty/whitespace-only content returns empty result (no error).
        - Matches shorter than MIN_CONTENT_LENGTH after strip are skipped.
        - Deduplication is NOT performed here — caller (KnowledgeStore) handles it.
        """
        facts: list[KnowledgeFact] = []
        skipped = 0

        if not content or not content.strip():
            return ExtractionResult(facts=[], skipped_count=0)

        seen_texts: set[str] = set()

        for pattern_name, pattern in self.patterns.items():
            for match in pattern.finditer(content):
                matched_text = match.group(0).strip()

                if len(matched_text) < _MIN_CONTENT_LENGTH:
                    skipped += 1
                    continue

                # Skip duplicates within the same response
                if matched_text.lower() in seen_texts:
                    skipped += 1
                    continue
                seen_texts.add(matched_text.lower())

                extracted_tags = list(tags or [])
                extracted_tags.append(pattern_name)

                fact = KnowledgeFact.new(
                    content=matched_text,
                    source_session_id=source_session_id,
                    tags=extracted_tags,
                    confidence=1.0,
                )
                facts.append(fact)

        return ExtractionResult(facts=facts, skipped_count=skipped)
