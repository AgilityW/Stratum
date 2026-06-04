"""Watchlist acquisition — RSS and fixed URL acquisition.

Entry points: collect(domain, workspace, run_date) and collect_with_stats(...).
Dispatches by source.access to the right acquisition channel.

Channel modules:
  rss_channel   — RSS/Atom feeds
  url_channel   — trusted fixed URLs via direct_fetch/browser

All strategies return list[SearchResult]. The orchestrator uses collect_with_stats()
to merge the combined pool and persist source health.
"""

import sys
import time
from typing import Any

from stratum.sourcing.watchlist.keywords import load_keywords
from stratum.sourcing.watchlist.models import (
    CollectorRun,
    CollectorSourceStats,
    WatchlistRun,
    WatchlistSourceStats,
)
from stratum.sourcing.watchlist.registry import get_active_sources
from stratum.sourcing.discovery import SearchResult


RSS_ACCESS = {"rss"}
URL_ACCESS = {"direct_fetch", "browser"}

__all__ = [
    "CollectorRun",
    "CollectorSourceStats",
    "SearchResult",
    "WatchlistRun",
    "WatchlistSourceStats",
    "collect",
    "collect_with_stats",
]


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Backward-compatible watchlist API returning only results."""
    return collect_with_stats(domain, workspace, run_date).results


def collect_with_stats(
    domain: str,
    workspace: str,
    run_date: str,
    source_health: dict[str, dict[str, Any]] | None = None,
) -> WatchlistRun:
    """Search configured sources from ALL active sources across all access types.

    Reads source_registry from domain.yaml, dispatches by access type,
    and returns merged SearchResult list with per-source health stats.

    Pipeline contract: collect_with_stats() is the structured orchestrator API.
    Adding a new source acquisition method means adding/extending a channel
    module; pipeline code never changes.
    """
    sources = get_active_sources(domain, workspace, source_health=source_health)
    if not sources:
        return WatchlistRun(results=[], source_stats=[])

    keywords = load_keywords(domain, workspace)

    all_results: list[SearchResult] = []
    source_stats: list[WatchlistSourceStats] = []
    all_observations: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []

    for source in sources:
        access = source.get("access", "")
        sid = source.get("id", "?")
        locale = source.get("locale", "")
        category = source.get("category", "")
        started = time.perf_counter()

        try:
            outcome = _collect_source_by_channel(source, keywords, run_date)
            results = outcome.results
            all_observations.extend(outcome.observations)
            all_candidates.extend(outcome.candidates)
            access = outcome.access
            locale = outcome.locale
            category = outcome.category
            if outcome.status == "unsupported":
                print(f"  ⚠️  Unknown access type '{access}' for [{sid}]", file=sys.stderr)
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                source_stats.append(WatchlistSourceStats(
                    source=sid,
                    access="unknown",
                    status="unsupported",
                    hits=0,
                    duration_ms=elapsed,
                    locale=locale,
                    category=category,
                    error=f"unknown access type: {access}",
                ))
                continue

            if results:
                print(f"  ✅ [{access}] {sid}: {len(results)} articles", file=sys.stderr)
            else:
                print(f"  ⚠️  [{access}] {sid}: no articles", file=sys.stderr)

            all_results.extend(results)
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            dated = sum(1 for r in results if getattr(r, "published_at", None))
            source_stats.append(WatchlistSourceStats(
                source=sid,
                access=access,
                status=outcome.status,
                hits=len(results),
                duration_ms=elapsed,
                locale=locale,
                category=category,
                dated=dated,
                error=outcome.error,
            ))

        except Exception as e:
            print(f"  ⚠️  [{access}] {sid} error: {e}", file=sys.stderr)
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            status = (
                "unsupported"
                if e.__class__.__name__ == "BrowserWatchlistUnavailable"
                else "error"
            )
            source_stats.append(WatchlistSourceStats(
                source=sid,
                access=access or "unknown",
                status=status,
                hits=0,
                duration_ms=elapsed,
                locale=locale,
                category=category,
                error=str(e),
            ))

    return WatchlistRun(
        results=all_results,
        source_stats=source_stats,
        observations=all_observations,
        candidates=all_candidates,
    )


def _collect_source_by_channel(source: dict, keywords: list[str], run_date: str):
    """Dispatch one source to its acquisition channel."""
    access = source.get("access", "")
    if access in RSS_ACCESS:
        from stratum.sourcing.watchlist.rss_channel import collect_source

        return collect_source(source, keywords)
    if access in URL_ACCESS:
        from stratum.sourcing.watchlist.url_channel import collect_source

        try:
            return collect_source(source, run_date, keywords=keywords)
        except TypeError as exc:
            if "keyword" not in str(exc):
                raise
            return collect_source(source, run_date)
    from stratum.sourcing.watchlist.models import WatchlistChannelResult

    return WatchlistChannelResult(
        results=[],
        access="unknown",
        status="unsupported",
        locale=source.get("locale", ""),
        category=source.get("category", ""),
        error=f"unknown access type: {access}",
    )
