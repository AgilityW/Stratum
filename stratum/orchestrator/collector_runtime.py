"""Compatibility facade for legacy imports that still reference collector runtime.

The canonical watchlist orchestration surface lives in
`stratum.orchestrator.watchlist_runtime`. Keep this wrapper intentionally
narrow so compatibility does not implicitly expose every helper in the
canonical module.
"""

from stratum.orchestrator.watchlist_runtime import (
    CONFIG_PATH,
    load_raw_results,
    load_watchlist_source_health,
    run_watchlist,
    set_watchlist_selected_counts,
    update_post_collect_search_stats,
    watchlist_source_id,
    write_watchlist_health,
)

__all__ = [
    "CONFIG_PATH",
    "load_raw_results",
    "load_watchlist_source_health",
    "run_watchlist",
    "set_watchlist_selected_counts",
    "update_post_collect_search_stats",
    "watchlist_source_id",
    "write_watchlist_health",
]
