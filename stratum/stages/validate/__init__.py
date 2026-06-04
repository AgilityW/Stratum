"""Validate stage package.

Validate keeps stage orchestration in `validate.py` and matching/claim rules in
dedicated sibling policy modules. Internal imports should prefer
package-relative paths so validation logic can be reused directly.
"""

from .claim_validator import ClaimValidator, validate_overclaims
from .source_support import SourceDatePolicy, SourceSupportMatcher
from .validate import (
    _parse_source_line,
    load_articles,
    load_domain_config,
    parse_markdown,
    resolve_date_window,
    validate_briefing,
    validate_boilerplate,
    validate_item,
    validate_structured_output,
)

__all__ = [
    "ClaimValidator",
    "SourceDatePolicy",
    "SourceSupportMatcher",
    "_parse_source_line",
    "load_articles",
    "load_domain_config",
    "parse_markdown",
    "resolve_date_window",
    "validate_briefing",
    "validate_boilerplate",
    "validate_item",
    "validate_overclaims",
    "validate_structured_output",
]
