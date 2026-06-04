"""Normalize stage package.

Normalize keeps article-shaping orchestration in `normalize.py` and extraction
or matching algorithms in sibling modules. Internal imports should prefer
package-relative paths so the stage remains reusable as a package.
"""

from .extractors import (
    ClaimExtractor,
    EntityResolver,
    TermResolver,
    extract_entities,
    extract_numeric_claims,
    extract_terms,
    extract_typed_numeric_claims,
    extract_title_patterns,
)
from .normalize import (
    classify_artifact_type,
    classify_source_type,
    content_hash,
    determine_source_locale,
    load_domain_config,
    normalize_article,
    normalize_source_type,
    resolve_source_locale,
    resolve_source_type,
)
from .thread_matcher import ThreadKeywordMatcher, match_thread_keywords

__all__ = [
    "ClaimExtractor",
    "EntityResolver",
    "TermResolver",
    "ThreadKeywordMatcher",
    "classify_artifact_type",
    "classify_source_type",
    "content_hash",
    "determine_source_locale",
    "extract_entities",
    "extract_numeric_claims",
    "extract_terms",
    "extract_typed_numeric_claims",
    "extract_title_patterns",
    "load_domain_config",
    "match_thread_keywords",
    "normalize_article",
    "normalize_source_type",
    "resolve_source_locale",
    "resolve_source_type",
]
