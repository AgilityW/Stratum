"""Monitoring package for source health, engine health, and coverage gaps.

This package exposes deterministic monitoring helpers without tying callers to
individual module filenames.
"""

from .coverage import detect_gaps, generate_followup_queries, run_coverage_check, score_search_engine_health
from .engine_health import EngineHealthScorer
from .health import (
    ensure_channel_dir,
    get_dry_sources,
    get_non_contributing_sources,
    get_source_alerts,
    get_top_contributors,
    load_daily_records,
    rebuild_stats,
    write_daily_record,
)

__all__ = [
    "EngineHealthScorer",
    "detect_gaps",
    "ensure_channel_dir",
    "generate_followup_queries",
    "get_dry_sources",
    "get_non_contributing_sources",
    "get_source_alerts",
    "get_top_contributors",
    "load_daily_records",
    "rebuild_stats",
    "run_coverage_check",
    "score_search_engine_health",
    "write_daily_record",
]
