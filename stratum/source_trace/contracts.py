"""SourceTrace file and payload contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TraceFile:
    """Stable SourceTrace input or output filename."""

    key: str
    filename: str
    file_format: str


WATCHLIST_OBSERVATIONS = TraceFile("watchlist_observations", "watchlist_observations.jsonl", "jsonl")
DISCOVERY_OBSERVATIONS = TraceFile("discovery_observations", "discovery_observations.jsonl", "jsonl")
WATCHLIST_CANDIDATES = TraceFile("watchlist_candidates", "watchlist_candidates.jsonl", "jsonl")
DISCOVERY_CANDIDATES = TraceFile("discovery_candidates", "discovery_candidates.jsonl", "jsonl")
WATCHLIST_RESULTS = TraceFile("watchlist_results", "watchlist_results.json", "json")
RAW_RESULTS = TraceFile("raw", "raw.json", "json")

SOURCE_TRACE_SUMMARY = TraceFile("source_trace_summary", "source_trace_summary.json", "json")
SOURCE_QUALITY = TraceFile("source_quality", "source_quality.json", "json")
MISSED_SIGNALS = TraceFile("missed_signals", "missed_signals.json", "json")
DEDUPE_LOSS = TraceFile("dedupe_loss", "dedupe_loss.json", "json")
THREAD_ATTRIBUTION = TraceFile("thread_attribution", "thread_attribution.json", "json")
REPORT_IMPACT = TraceFile("report_impact", "report_impact.json", "json")
TEMPORAL_PROFILE = TraceFile("temporal_profile", "temporal_profile.json", "json")
POLICY_RECOMMENDATIONS = TraceFile("policy_recommendations", "policy_recommendations.json", "json")
OBSERVATION_HEALTH = TraceFile("observation_health", "observation_health.json", "json")
ISSUES = TraceFile("issues", "issues.json", "json")
SOURCE_TRACE_CHARTS = TraceFile("source_trace_charts", "source_trace_charts.md", "markdown")

INPUT_FILES = (
    WATCHLIST_OBSERVATIONS,
    DISCOVERY_OBSERVATIONS,
    WATCHLIST_CANDIDATES,
    DISCOVERY_CANDIDATES,
    WATCHLIST_RESULTS,
    RAW_RESULTS,
)

OUTPUT_FILES = (
    SOURCE_TRACE_SUMMARY,
    SOURCE_QUALITY,
    MISSED_SIGNALS,
    DEDUPE_LOSS,
    THREAD_ATTRIBUTION,
    REPORT_IMPACT,
    TEMPORAL_PROFILE,
    POLICY_RECOMMENDATIONS,
    OBSERVATION_HEALTH,
    ISSUES,
    SOURCE_TRACE_CHARTS,
)


def output_filename(key: str) -> str:
    """Return the stable output filename for a SourceTrace output key."""
    for spec in OUTPUT_FILES:
        if spec.key == key:
            return spec.filename
    raise KeyError(f"unknown SourceTrace output key: {key}")


def validate_output_payload(key: str, payload: Any) -> None:
    """Lightweight contract guard for runner outputs."""
    if key == "source_trace_charts":
        if not isinstance(payload, str):
            raise TypeError(f"{key} must be a markdown string payload")
        return
    if key in {"source_quality", "missed_signals", "policy_recommendations"}:
        if not isinstance(payload, list):
            raise TypeError(f"{key} must be a list payload")
        return
    if not isinstance(payload, dict):
        raise TypeError(f"{key} must be an object payload")
