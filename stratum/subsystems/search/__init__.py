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
    query_objects = []
    for q in queries:
        include_domains = q.get("include_domains") or []
        if isinstance(include_domains, str):
            include_domains = [include_domains]
        query_objects.append(
            Query(
                id=q["id"],
                text=q["text"],
                locale=q["locale"],
                intent=q.get("intent", "detection"),
                dimension=q.get("dimension", "general"),
                include_domains=list(include_domains),
            )
        )

    # Create engines. Engines without API keys are intentionally omitted; the
    # executor records per-query diagnostics and can fall back to keyed engines.
    engines = create_engines(config["engines"], api_keys)
    if not engines:
        print("WARNING: No usable search engines configured", file=sys.stderr)

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
        min_per_source_type=config.get("min_per_source_type", {}),
        max_per_entity=config.get("max_per_entity", 0),
    )
    diagnostics = build_diagnostics(
        queries=query_objects,
        raw_results=raw_results,
        curated_results=curated,
        query_stats=query_stats,
        config=config,
    )

    return ResultSet(
        results=curated,
        raw_results=raw_results,
        stats=query_stats,
        date=date,
        total_raw=total_raw,
        total_curated=len(curated),
        diagnostics=diagnostics,
    )


def build_diagnostics(
    queries: list[Any],
    raw_results: list[Any],
    curated_results: list[Any],
    query_stats: list[Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build actionable Search quality diagnostics for raw.stats.json."""
    query_counts: dict[str, int] = {}
    for q in queries:
        locale = _diagnostic_key(q.locale)
        query_counts[locale] = query_counts.get(locale, 0) + 1

    raw_by_locale = _count_results(raw_results, "locale")
    curated_by_locale = _count_results(curated_results, "locale")
    raw_by_type = _count_results(raw_results, "source_type_hint")
    curated_by_type = _count_results(curated_results, "source_type_hint")
    raw_by_dimension = _count_results(raw_results, "query_dimension")
    curated_by_dimension = _count_results(curated_results, "query_dimension")

    diagnostics = {
        "raw_by_locale": raw_by_locale,
        "curated_by_locale": curated_by_locale,
        "raw_by_source_type": raw_by_type,
        "curated_by_source_type": curated_by_type,
        "raw_by_dimension": raw_by_dimension,
        "curated_by_dimension": curated_by_dimension,
        "dimension_coverage": _dimension_coverage(query_stats, raw_by_dimension, curated_by_dimension),
        "locale_coverage": _locale_coverage(config.get("routing", {}), query_counts, raw_by_locale, curated_by_locale),
        "source_type_gaps": _source_type_gaps(
            config.get("min_per_source_type", {}), raw_by_type, curated_by_type
        ),
        "domain_filter_coverage": _domain_filter_coverage(
            query_stats, raw_results, curated_results
        ),
        "top_source_domains": _top_source_domains(raw_results, curated_results),
        "low_yield_queries": [
            s.to_dict()
            for s in query_stats
            if s.status not in {"success", "fallback"} or s.results_count == 0
        ],
    }
    return diagnostics


def _diagnostic_key(value: Any) -> str:
    """Normalize diagnostic grouping keys from external data."""
    if value is None or value is False or value == "":
        return "unknown"
    return str(value)


def _count_results(results: list[Any], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        value = _diagnostic_key(getattr(result, attr, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _locale_coverage(
    routing: dict[str, list[str]],
    query_counts: dict[str, int],
    raw_by_locale: dict[str, int],
    curated_by_locale: dict[str, int],
) -> list[dict[str, Any]]:
    locales = sorted(
        _diagnostic_key(locale)
        for locale in (set(routing) | set(query_counts) | set(raw_by_locale) | set(curated_by_locale))
    )
    return [
        {
            "locale": locale,
            "queries": query_counts.get(locale, 0),
            "raw": raw_by_locale.get(locale, 0),
            "curated": curated_by_locale.get(locale, 0),
        }
        for locale in locales
    ]


def _dimension_coverage(
    query_stats: list[Any],
    raw_by_dimension: dict[str, int],
    curated_by_dimension: dict[str, int],
) -> list[dict[str, Any]]:
    query_counts: dict[str, int] = {}
    for stat in query_stats:
        dimension = getattr(stat, "dimension", "general") or "general"
        query_counts[dimension] = query_counts.get(dimension, 0) + 1

    dimensions = sorted(set(query_counts) | set(raw_by_dimension) | set(curated_by_dimension))
    return [
        {
            "dimension": dimension,
            "queries": query_counts.get(dimension, 0),
            "raw": raw_by_dimension.get(dimension, 0),
            "curated": curated_by_dimension.get(dimension, 0),
        }
        for dimension in dimensions
    ]


def _source_type_gaps(
    minimums: dict[str, int],
    raw_by_type: dict[str, int],
    curated_by_type: dict[str, int],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for source_type, minimum in sorted(minimums.items()):
        curated = curated_by_type.get(source_type, 0)
        if curated >= minimum:
            continue
        gaps.append({
            "source_type": source_type,
            "minimum": minimum,
            "raw_available": raw_by_type.get(source_type, 0),
            "curated": curated,
            "shortfall": minimum - curated,
        })
    return gaps


def _domain_filter_coverage(
    query_stats: list[Any],
    raw_results: list[Any],
    curated_results: list[Any],
) -> list[dict[str, Any]]:
    """Summarize source-scoped query yield by configured include domain."""
    domains_by_query: dict[str, list[str]] = {}
    query_counts: dict[str, int] = {}
    failed_counts: dict[str, int] = {}
    for stat in query_stats:
        domains = [
            str(domain).strip()
            for domain in (getattr(stat, "include_domains", []) or [])
            if str(domain).strip()
        ]
        if not domains:
            continue
        domains_by_query[getattr(stat, "query_id", "")] = domains
        for domain in domains:
            query_counts[domain] = query_counts.get(domain, 0) + 1
            if getattr(stat, "status", "") not in {"success", "fallback"}:
                failed_counts[domain] = failed_counts.get(domain, 0) + 1

    if not query_counts:
        return []

    raw_counts = _domain_filter_result_counts(raw_results, domains_by_query)
    curated_counts = _domain_filter_result_counts(curated_results, domains_by_query)
    return [
        {
            "include_domain": domain,
            "queries": query_counts.get(domain, 0),
            "failed_queries": failed_counts.get(domain, 0),
            "raw": raw_counts.get(domain, 0),
            "curated": curated_counts.get(domain, 0),
        }
        for domain in sorted(query_counts)
    ]


def _domain_filter_result_counts(
    results: list[Any],
    domains_by_query: dict[str, list[str]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        query_domains = domains_by_query.get(getattr(result, "query_id", ""), [])
        source_domain = getattr(result, "source_domain", "") or "unknown"
        for domain in query_domains:
            if _domain_matches(source_domain, domain):
                counts[domain] = counts.get(domain, 0) + 1
    return counts


def _domain_matches(source_domain: str, include_domain: str) -> bool:
    source = (source_domain or "").lower()
    target = (include_domain or "").lower()
    if source.startswith("www."):
        source = source[4:]
    if target.startswith("www."):
        target = target[4:]
    return source == target or source.endswith(f".{target}")


def _top_source_domains(
    raw_results: list[Any],
    curated_results: list[Any],
    limit: int = 20,
) -> list[dict[str, Any]]:
    raw_counts = _count_results(raw_results, "source_domain")
    curated_counts = _count_results(curated_results, "source_domain")
    domains = sorted(raw_counts, key=lambda d: (-raw_counts[d], d))[:limit]
    return [
        {
            "source_domain": domain,
            "raw": raw_counts.get(domain, 0),
            "curated": curated_counts.get(domain, 0),
        }
        for domain in domains
    ]


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
