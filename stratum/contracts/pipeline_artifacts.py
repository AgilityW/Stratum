"""Pipeline artifact filename contract.

This module owns stable stage handoff filenames. Orchestrators and DB artifact
indexing should import these constants instead of repeating literal names.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactSpec:
    """One named artifact emitted or consumed by the pipeline."""

    key: str
    filename: str
    artifact_type: str
    required: bool = False


RAW_RESULTS = ArtifactSpec("raw", "raw.json", "raw", required=True)
WATCHLIST_OBSERVATIONS = ArtifactSpec("watchlist_observations", "watchlist_observations.jsonl", "watchlist_observations")
WATCHLIST_RESULTS = ArtifactSpec("watchlist_results", "watchlist_results.json", "watchlist_results")
WATCHLIST_CANDIDATES = ArtifactSpec("watchlist_candidates", "watchlist_candidates.jsonl", "watchlist_candidates")
DISCOVERY_OBSERVATIONS = ArtifactSpec("discovery_observations", "discovery_observations.jsonl", "discovery_observations")
DISCOVERY_CANDIDATES = ArtifactSpec("discovery_candidates", "discovery_candidates.jsonl", "discovery_candidates")
RAW_STATS = ArtifactSpec("search_stats", "raw.stats.json", "raw_stats")
VERIFIED_ARTICLES = ArtifactSpec("verified", "verified.jsonl", "verified", required=True)
VERIFY_STATS = ArtifactSpec("verify_stats", "verified.stats.json", "verified_stats")
NORMALIZED_ARTICLES = ArtifactSpec("articles", "articles.jsonl", "articles", required=True)
STORY_CLUSTERS = ArtifactSpec("clusters", "clusters.json", "clusters", required=True)
BRIEFING_PLAN = ArtifactSpec("briefing_plan", "briefing_plan.json", "briefing_plan")
BRIEFING_CHUNKS = ArtifactSpec("briefing_chunks", "briefing_chunks.json", "briefing_chunks")
EDIT_TRACE = ArtifactSpec("edit_trace", "edit_trace.json", "edit_trace")
VALIDATE_REPORT = ArtifactSpec("validate_report", "validate_report.json", "validate_report")
REPAIR_REPORT = ArtifactSpec("repair_report", "repair_report.json", "repair_report")
RUN_MANIFEST = ArtifactSpec("run_manifest", "run_manifest.json", "run_manifest")
EVENT_THREADS = ArtifactSpec("event_threads", "event-threads.json", "event_threads")
THREAD_KEYWORDS = ArtifactSpec("thread_keywords", "thread_keywords.json", "thread_keywords")


DATA_DIR_ARTIFACTS = (
    RAW_RESULTS,
    WATCHLIST_OBSERVATIONS,
    WATCHLIST_RESULTS,
    WATCHLIST_CANDIDATES,
    DISCOVERY_OBSERVATIONS,
    DISCOVERY_CANDIDATES,
    RAW_STATS,
    VERIFIED_ARTICLES,
    VERIFY_STATS,
    NORMALIZED_ARTICLES,
    STORY_CLUSTERS,
    BRIEFING_PLAN,
    BRIEFING_CHUNKS,
    EDIT_TRACE,
    VALIDATE_REPORT,
    REPAIR_REPORT,
    RUN_MANIFEST,
)


REPORT_ARTIFACT_TYPES = {
    spec.key: spec.artifact_type
    for spec in DATA_DIR_ARTIFACTS
}


LEGACY_RAW_ALIASES = (
    "raw.full.json",
    "raw_full.json",
    "raw.curated.json",
    "raw_curated.json",
    "raw.search.json",
    "raw.watchlist.json",
    "search_raw.json",
    "watchlist_raw.json",
)


LEGACY_WATCHLIST_SIDECAR_ALIASES = (
    "collector_stats.json",
)
