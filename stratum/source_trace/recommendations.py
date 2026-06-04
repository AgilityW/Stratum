"""Policy recommendations derived from SourceTrace analyzer outputs."""

from __future__ import annotations

from typing import Any


def generate_recommendations(
    quality: list[dict[str, Any]],
    *,
    missed_signals: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
    temporal_profile: dict[str, Any] | None = None,
    observation_health: dict[str, Any] | None = None,
    issues: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate source budget, admission, and extraction tuning suggestions."""
    missed_signals = missed_signals or []
    provenance = provenance or {}
    observation_health = observation_health or {}
    issues = issues or {}
    temporal_by_source = {
        row.get("source", ""): row
        for row in temporal_profile.get("sources", [])
    } if temporal_profile else {}
    missed_by_source: dict[str, int] = {}
    for item in missed_signals:
        source = item.get("source", "unknown")
        missed_by_source[source] = missed_by_source.get(source, 0) + 1

    recs = []
    for row in quality:
        source = row.get("source", "unknown")
        tier = row.get("tier", "")
        reject_rate = float(row.get("reject_rate", 0.0) or 0.0)
        temporal = temporal_by_source.get(source, {})
        if tier == "core":
            recs.append(_rec(source, "increase_budget", "high source quality and downstream impact"))
        if tier == "noisy" and reject_rate >= 0.75:
            recs.append(_rec(source, "tighten_admission", "high reject rate indicates noisy candidates"))
        if missed_by_source.get(source, 0):
            recs.append(_rec(source, "review_rejected_candidates", "rejected candidates later matched important records"))
        if temporal.get("temporal_tier") == "undated":
            recs.append(_rec(source, "improve_date_extraction", "source has low dated-rate in temporal profile"))

    for layer in ("watchlist", "discovery"):
        for row in observation_health.get(layer, {}).get("sources", []):
            if row.get("health_status") == "needs_adapter_review":
                recs.append(_rec(row.get("source", "unknown"), "review_parser_adapter", "observation health suggests parser or provider extraction problems"))

    for issue in issues.get("issues", []):
        if issue.get("code") == "all_candidates_rejected":
            recs.append(_rec(issue.get("source", "unknown"), "review_admission_threshold", issue.get("message", "")))

    if provenance.get("totals", {}).get("deduped_paths", 0) > 0:
        recs.append({
            "scope": "global",
            "action": "preserve_multi_path_provenance",
            "reason": "multiple acquisition paths resolve to the same canonical URLs",
            "priority": "medium",
        })

    return recs


def _rec(source: str, action: str, reason: str) -> dict[str, Any]:
    return {
        "scope": "source",
        "source": source,
        "action": action,
        "reason": reason,
        "priority": "high" if action in {"review_rejected_candidates", "improve_date_extraction"} else "medium",
    }
