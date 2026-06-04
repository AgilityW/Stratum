#!/usr/bin/env python3
"""Legacy search-stage wrapper for `stratum.stages.acquisition.acquisition`.

The canonical stage is acquisition. This module exists only for old CLI/test
entrypoints that still import or execute `stratum/stages/search/search.py`.
"""

from stratum.stages.acquisition import (
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


if __name__ == "__main__":
    main()
