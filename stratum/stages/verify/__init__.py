"""Verify stage package.

Verify keeps stage orchestration in `verify.py` and acceptance/freshness policy
logic in sibling modules. External callers should prefer this package surface
for stable imports.
"""

from .evidence_acceptance import (
    EvidenceAcceptancePolicy,
    check_duplicate,
    check_magnitude,
    check_platform_admission,
    extract_domain,
    is_blocklisted,
    is_low_priority_domain,
)
from .freshness_policy import (
    FreshnessPolicy,
    background_flags_for_date_failure,
    date_confidence_for_source,
    date_confidence_meets_minimum,
    validate_date,
)
from .verify import (
    build_verification_stats,
    default_stats_path,
    extract_date_from_metadata,
    load_domain_config,
    parse_date,
    verify_article,
)

__all__ = [
    "EvidenceAcceptancePolicy",
    "FreshnessPolicy",
    "background_flags_for_date_failure",
    "build_verification_stats",
    "check_duplicate",
    "check_magnitude",
    "check_platform_admission",
    "date_confidence_for_source",
    "date_confidence_meets_minimum",
    "default_stats_path",
    "extract_date_from_metadata",
    "extract_domain",
    "is_blocklisted",
    "is_low_priority_domain",
    "load_domain_config",
    "parse_date",
    "validate_date",
    "verify_article",
]
