"""Stable package surface for the acquisition stage."""

from .acquisition import (
    discovery_candidate_rows,
    discovery_candidates_path,
    discovery_observations_path,
    load_existing_raw,
    load_queries_flat,
    load_queries_from_db,
    main,
    merge_raw_results,
    resolve_queries,
    skipped_query_stats,
    split_queries_by_coverage,
    write_jsonl,
)

__all__ = [
    "discovery_candidate_rows",
    "discovery_candidates_path",
    "discovery_observations_path",
    "load_existing_raw",
    "load_queries_flat",
    "load_queries_from_db",
    "main",
    "merge_raw_results",
    "resolve_queries",
    "skipped_query_stats",
    "split_queries_by_coverage",
    "write_jsonl",
]
