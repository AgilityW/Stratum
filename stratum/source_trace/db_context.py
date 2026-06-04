"""SourceTrace DB read-model context contract."""

from __future__ import annotations

from typing import Any


DB_CONTEXT_KEYS = (
    "articles",
    "events",
    "threads",
    "report_items",
    "evidence_links",
    "judgments",
    "persisted_articles",
)


def empty_db_context() -> dict[str, list[dict[str, Any]]]:
    """Return an empty DB context with all expected keys present."""
    return {key: [] for key in DB_CONTEXT_KEYS}


def normalize_db_context(context: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Normalize caller-provided DB read-model records for SourceTrace."""
    normalized = empty_db_context()
    if not context:
        return normalized
    for key in DB_CONTEXT_KEYS:
        value = context.get(key, [])
        normalized[key] = value if isinstance(value, list) else []
    return normalized
