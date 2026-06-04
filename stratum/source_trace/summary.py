"""Build SourceTrace summary payloads."""

from __future__ import annotations

from typing import Any


def build_summary(
    *,
    observations: dict[str, Any],
    funnel: dict[str, Any],
    quality: list[dict[str, Any]],
    missed_signals: list[dict[str, Any]],
    provenance: dict[str, Any],
    observation_health: dict[str, Any],
    issues: dict[str, Any],
    recommendations: list[dict[str, Any]],
    input_status: dict[str, Any] | None = None,
    input_errors: dict[str, int] | None = None,
    conversion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the top-level SourceTrace run summary."""
    return {
        "version": "0.1",
        "status": (input_status or {}).get("status", "ok"),
        "input_status": input_status or {"status": "ok"},
        "input_errors": input_errors or {},
        "observation_totals": observations.get("totals", {}),
        "funnel_totals": funnel.get("totals", {}),
        "conversion_totals": (conversion or {}).get("totals", {}),
        "quality": {
            "source_count": len(quality),
            "core_sources": sum(1 for row in quality if row.get("tier") == "core"),
            "noisy_sources": sum(1 for row in quality if row.get("tier") == "noisy"),
            "top_sources": quality[:10],
        },
        "missed_signals": {
            "count": len(missed_signals),
            "top": missed_signals[:10],
        },
        "provenance_totals": provenance.get("totals", {}),
        "observation_health_totals": {
            "watchlist": observation_health.get("watchlist", {}).get("totals", {}),
            "discovery": observation_health.get("discovery", {}).get("totals", {}),
        },
        "issues": issues.get("totals", {}),
        "recommendations": {
            "count": len(recommendations),
            "top": recommendations[:10],
        },
    }
