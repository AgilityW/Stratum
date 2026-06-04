"""Source quality scoring from SourceTrace funnel and impact records."""

from __future__ import annotations

from typing import Any


def score_sources(
    funnel: dict[str, Any],
    *,
    impact: dict[str, Any] | None = None,
    novelty: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Score sources using conversion, noise, novelty, and report impact."""
    impact_by_source = {
        row.get("source", ""): row
        for row in (impact or {}).get("sources", [])
    }
    novelty = novelty or {}
    scored = []
    for row in funnel.get("sources", []):
        source = row.get("source", "unknown")
        impact_row = impact_by_source.get(source, {})
        novelty_score = float(novelty.get(source, 0.0) or 0.0)
        score = (
            0.25 * float(row.get("admission_rate", 0.0) or 0.0)
            + 0.20 * float(row.get("consumption_rate", 0.0) or 0.0)
            + 0.20 * float(row.get("verified_rate", 0.0) or 0.0)
            + 0.20 * float(row.get("report_rate", 0.0) or 0.0)
            + 0.15 * novelty_score
        )
        noise_penalty = 0.20 * float(row.get("reject_rate", 0.0) or 0.0)
        impact_bonus = min(float(impact_row.get("impact_score", 0.0) or 0.0), 1.0) * 0.15
        quality_score = round(max(0.0, min(1.0, score - noise_penalty + impact_bonus)), 4)
        scored.append({
            "source": source,
            "quality_score": quality_score,
            "tier": _tier(quality_score),
            "seen": row.get("seen", 0),
            "admitted": row.get("admitted", 0),
            "consumed": row.get("consumed", 0),
            "reported": row.get("reported", 0),
            "reject_rate": row.get("reject_rate", 0.0),
            "novelty_score": round(novelty_score, 4),
            "impact_score": impact_row.get("impact_score", 0.0),
        })
    return sorted(scored, key=lambda item: (-item["quality_score"], item["source"]))


def _tier(score: float) -> str:
    if score >= 0.75:
        return "core"
    if score >= 0.5:
        return "useful"
    if score >= 0.25:
        return "watch"
    return "noisy"
