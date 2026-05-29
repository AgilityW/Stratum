"""Search Subsystem — public API.

Usage:
    from stratum.subsystems.search import run_search

    config = load_search_config(domain, workspace)
    api_keys = load_api_keys()
    result_set = run_search(queries, config, api_keys, date)
    raw = result_set.to_raw_json()
    stats = result_set.to_stats_json()
"""

import sys
from typing import Any


def run_search(
    queries: list[dict],
    config: dict[str, Any],
    api_keys: dict[str, str],
    date: str,
    workers: int = 8,
):
    """Run the full search pipeline: execute → curate → return ResultSet.

    Args:
        queries: List of query dicts with id, text, locale, intent
        config: Search config from load_search_config()
        api_keys: API keys from load_api_keys()
        date: Run date YYYY-MM-DD
        workers: Concurrent workers

    Returns:
        ResultSet with curated results and query statistics
    """
    # Lazy imports to avoid module-level dependencies
    from stratum.subsystems.search.config import load_api_keys, load_search_config
    from stratum.subsystems.search.curator import curate
    from stratum.subsystems.search.engine import create_engines
    from stratum.subsystems.search.executor import execute
    from stratum.subsystems.search.models import Query, ResultSet

    # Convert dicts to Query objects
    query_objects = [
        Query(id=q["id"], text=q["text"], locale=q["locale"], intent=q.get("intent", "detection"))
        for q in queries
    ]

    # Create engines
    engines = create_engines(config["engines"], api_keys)
    if not engines:
        print("WARNING: No search engines configured", file=sys.stderr)
        return ResultSet(date=date)

    # Build executor params
    max_rps = {name: cfg["max_rps"] for name, cfg in config["engines"].items()}
    max_retries = {name: cfg["max_retries"] for name, cfg in config["engines"].items()}
    backoff_base = {name: cfg["backoff_base"] for name, cfg in config["engines"].items()}

    # Execute
    raw_results, query_stats = execute(
        queries=query_objects,
        engines=engines,
        routing=config["routing"],
        max_rps=max_rps,
        max_retries=max_retries,
        backoff_base=backoff_base,
        date=date,
        workers=workers,
    )

    total_raw = len(raw_results)

    # Curate: domain extraction → classification → scoring → pruning
    curated = curate(
        results=raw_results,
        run_date=date,
        source_weights=config["source_weights"],
        classifications=config["classifications"],
        entities=config["entities"],
        terms=config["terms"],
        max_per_locale=config["max_per_locale"],
        max_per_source=config["max_per_source"],
        total_cap=config["total_cap"],
    )

    return ResultSet(
        results=curated,
        stats=query_stats,
        date=date,
        total_raw=total_raw,
        total_curated=len(curated),
    )


__all__ = ["run_search", "load_search_config", "load_api_keys", "Query", "ResultSet"]


def __getattr__(name: str):
    """Lazy-load config functions to avoid yaml import at module level."""
    if name in ("load_search_config", "load_api_keys"):
        from stratum.subsystems.search.config import load_api_keys, load_search_config
        return locals()[name]
    if name in ("Query", "ResultSet"):
        from stratum.subsystems.search.models import Query, ResultSet
        return locals()[name]
    raise AttributeError(f"module 'stratum.subsystems.search' has no attribute '{name}'")
