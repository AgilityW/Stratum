"""Policy feedback from signal bursts."""

from __future__ import annotations

from typing import Any


def generate_recommendations(bursts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate query, source, and report-synthesis recommendations."""
    recs = []
    for burst in bursts:
        if burst.get("confidence") in {"high", "medium"}:
            recs.append({
                "scope": "report_synthesis",
                "action": burst.get("recommended_report_treatment", "watch_item"),
                "label": burst.get("label", ""),
                "reason": f"{burst.get('classification')} burst with score {burst.get('burst_score')}",
                "priority": "high" if burst.get("confidence") == "high" else "medium",
            })
        if burst.get("classification") == "emerging":
            for term in burst.get("terms", []):
                recs.append({
                    "scope": "query_policy",
                    "action": "consider_query_expansion",
                    "term": term,
                    "label": burst.get("label", ""),
                    "reason": "emerging burst term may need dedicated follow-up queries",
                    "priority": "medium",
                })
    return recs
