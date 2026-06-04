"""Enrich stage package.

Enrich keeps date-extraction orchestration in `enrich.py`. External callers
should prefer this package surface for stable imports.
"""

from .enrich import (
    DATE_PATTERNS,
    enrich_article,
    extract_date,
    extract_date_from_text,
    extract_date_from_url,
    extract_date_from_web,
    is_plausible_publication_date,
    parse_date_from_match,
)

__all__ = [
    "DATE_PATTERNS",
    "enrich_article",
    "extract_date",
    "extract_date_from_text",
    "extract_date_from_url",
    "extract_date_from_web",
    "is_plausible_publication_date",
    "parse_date_from_match",
]
