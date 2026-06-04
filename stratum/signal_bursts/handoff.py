"""Report synthesis handoff records for Signal Bursts."""

from __future__ import annotations

from typing import Any


def build_handoff(bursts: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    """Build compact report-synthesis handoff records."""
    handoff = []
    for burst in bursts[:limit]:
        handoff.append({
            "label": burst.get("label", ""),
            "classification": burst.get("classification", ""),
            "burst_score": burst.get("burst_score", 0.0),
            "confidence": burst.get("confidence", "low"),
            "terms": burst.get("terms", []),
            "why_now": _why_now(burst),
            "evidence_strength": burst.get("score_components", {}),
            "linked_threads": burst.get("links", {}).get("threads", []),
            "linked_events": burst.get("links", {}).get("events", []),
            "representative_evidence": burst.get("representative_titles", []),
            "recommended_report_treatment": burst.get("recommended_report_treatment", ""),
        })
    return handoff


def _why_now(burst: dict[str, Any]) -> str:
    classification = burst.get("classification", "normal")
    source_count = burst.get("source_count", 0)
    raw_count = burst.get("raw_count", 0)
    return (
        f"{classification} signal across {source_count} sources with "
        f"{raw_count} raw-evidence hits"
    )
