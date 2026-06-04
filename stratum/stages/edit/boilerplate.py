"""Compatibility wrapper for shared stage boilerplate helpers."""

from stratum.stages.boilerplate import (
    BoilerplateHit,
    artifact_boilerplate_violations,
    boilerplate_hits,
    build_boilerplate_rules,
    clean_article_evidence,
    clean_evidence_text,
    source_domain,
)

__all__ = [
    "BoilerplateHit",
    "artifact_boilerplate_violations",
    "boilerplate_hits",
    "build_boilerplate_rules",
    "clean_article_evidence",
    "clean_evidence_text",
    "source_domain",
]
