"""Compatibility package surface for legacy search-stage imports."""

from .search import (
    discovery_candidate_rows,
    load_queries_flat,
    load_queries_from_db,
    main,
    merge_raw_results,
    resolve_queries,
    skipped_query_stats,
    split_queries_by_coverage,
)

__all__ = [
    "discovery_candidate_rows",
    "load_queries_flat",
    "load_queries_from_db",
    "main",
    "merge_raw_results",
    "resolve_queries",
    "skipped_query_stats",
    "split_queries_by_coverage",
]
