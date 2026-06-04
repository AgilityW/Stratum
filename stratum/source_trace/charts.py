"""Mermaid chart rendering for SourceTrace outputs."""

from __future__ import annotations

from typing import Any


def build_charts(
    *,
    summary: dict[str, Any],
    quality: list[dict[str, Any]],
    observation_health: dict[str, Any],
) -> dict[str, str]:
    """Build Mermaid chart snippets for SourceTrace review."""
    return {
        "funnel": funnel_chart(summary.get("funnel_totals", {})),
        "quality": quality_chart(quality),
        "observation_health": observation_health_chart(observation_health),
    }


def charts_markdown(charts: dict[str, str]) -> str:
    """Render chart snippets into one Markdown artifact."""
    sections = ["# SourceTrace Charts", ""]
    for title, chart in charts.items():
        sections.extend([f"## {title.replace('_', ' ').title()}", "", "```mermaid", chart, "```", ""])
    return "\n".join(sections).rstrip() + "\n"


def funnel_chart(totals: dict[str, Any]) -> str:
    """Render the evidence lifecycle funnel as a Mermaid flowchart."""
    observed = int(totals.get("seen", totals.get("observed", 0)) or 0)
    admitted = int(totals.get("admitted", 0) or 0)
    consumed = int(totals.get("consumed", 0) or 0)
    verified = int(totals.get("verified", 0) or 0)
    reported = int(totals.get("reported", 0) or 0)
    persisted = int(totals.get("persisted", 0) or 0)
    return "\n".join([
        "flowchart LR",
        f'  observed["Observed<br/>{observed}"] --> admitted["Admitted<br/>{admitted}"]',
        f'  admitted --> consumed["Consumed<br/>{consumed}"]',
        f'  consumed --> verified["Verified<br/>{verified}"]',
        f'  verified --> reported["Reported<br/>{reported}"]',
        f'  reported --> persisted["Persisted<br/>{persisted}"]',
    ])


def quality_chart(quality: list[dict[str, Any]], *, limit: int = 8) -> str:
    """Render top source quality scores as Mermaid xychart."""
    rows = quality[:limit]
    labels = [_label(str(row.get("source", "unknown"))) for row in rows]
    values = [round(float(row.get("quality_score", 0.0) or 0.0), 3) for row in rows]
    ymax = max(values + [1.0])
    return "\n".join([
        "xychart-beta",
        '  title "Source Quality"',
        f"  x-axis [{', '.join(labels)}]",
        f'  y-axis "score" 0 --> {ymax}',
        f"  bar [{', '.join(str(value) for value in values)}]",
    ])


def observation_health_chart(observation_health: dict[str, Any]) -> str:
    """Render observation totals by layer."""
    watchlist = int(observation_health.get("watchlist", {}).get("totals", {}).get("observations", 0) or 0)
    discovery = int(observation_health.get("discovery", {}).get("totals", {}).get("observations", 0) or 0)
    candidates = (
        int(observation_health.get("watchlist", {}).get("totals", {}).get("candidates", 0) or 0)
        + int(observation_health.get("discovery", {}).get("totals", {}).get("candidates", 0) or 0)
    )
    return "\n".join([
        "xychart-beta",
        '  title "Observation Health"',
        "  x-axis [watchlist, discovery, candidates]",
        f'  y-axis "records" 0 --> {max(watchlist, discovery, candidates, 1)}',
        f"  bar [{watchlist}, {discovery}, {candidates}]",
    ])


def _label(value: str) -> str:
    value = value.replace('"', "").replace(",", " ").strip() or "unknown"
    if len(value) > 18:
        value = value[:15] + "..."
    return f'"{value}"'
