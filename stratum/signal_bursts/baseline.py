"""Historical baseline comparison for signal bursts."""

from __future__ import annotations

from typing import Any


def classify_against_baseline(candidate: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    """Classify candidate as emerging/intensifying/continuing/resurfacing/noise."""
    baseline = baseline or {}
    term_baseline = baseline.get("terms", {})
    expected = sum(float(term_baseline.get(term, {}).get("average_count", 0.0) or 0.0) for term in candidate.get("terms", []))
    observed = float(candidate.get("observed_count", 0.0) or 0.0)
    ratio = observed / max(expected, 1.0)
    if expected == 0 and observed > 0:
        classification = "emerging"
    elif ratio >= 2.0:
        classification = "intensifying"
    elif observed >= expected and expected >= 5:
        classification = "continuing_hot"
    elif baseline.get("recently_cold") and observed > 0:
        classification = "resurfacing"
    else:
        classification = "normal"
    return {
        "baseline_expected": round(expected, 4),
        "baseline_ratio": round(ratio, 4),
        "classification": classification,
    }
