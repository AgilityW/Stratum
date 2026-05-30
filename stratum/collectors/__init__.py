"""Collectors — content acquisition beyond search engines.

Entry points: collect(domain, workspace, run_date) and collect_with_stats(...).
Dispatches by source.access to the right strategy module.

Strategy modules:
  direct_fetch  — HTTP GET → HTML parse (heading-first + read-more fallback)
  rss           — HTTP GET → XML parse (RSS 2.0 + Atom)
  browser       — headless Chrome via Playwright

All strategies return list[SearchResult]. The orchestrator uses collect_with_stats()
to merge the combined pool and persist source health.
"""

import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

from stratum.collectors.keywords import load_keywords
from stratum.collectors.registry import get_active_sources
from stratum.subsystems.search.models import SearchResult


@dataclass
class CollectorSourceStats:
    """Per-source collector health record for monitoring."""

    source: str
    access: str
    status: str
    hits: int
    duration_ms: float
    locale: str = ""
    category: str = ""
    dated: int = 0
    selected: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CollectorRun:
    """Collector results plus structured source-level health."""

    results: list[SearchResult]
    source_stats: list[CollectorSourceStats]

    def stats_json(self, domain: str, run_date: str) -> dict[str, Any]:
        return {
            "domain": domain,
            "date": run_date,
            "total_results": len(self.results),
            "sources": [s.to_dict() for s in self.source_stats],
        }


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Backward-compatible collector API returning only results."""
    return collect_with_stats(domain, workspace, run_date).results


def collect_with_stats(domain: str, workspace: str, run_date: str) -> CollectorRun:
    """Collect articles from ALL active sources across all access types.

    Reads source_registry from domain.yaml, dispatches by access type,
    and returns merged SearchResult list with per-source health stats.

    Pipeline contract: collect_with_stats() is the structured orchestrator API.
    Adding a new access type = add strategy module + register here.
    Pipeline code never changes.
    """
    sources = get_active_sources(domain, workspace)
    if not sources:
        return CollectorRun(results=[], source_stats=[])

    keywords = load_keywords(domain, workspace)

    all_results: list[SearchResult] = []
    source_stats: list[CollectorSourceStats] = []

    for source in sources:
        access = source.get("access", "")
        sid = source.get("id", "?")
        locale = source.get("locale", "")
        category = source.get("category", "")
        started = time.perf_counter()
        warning = ""

        try:
            if access == "direct_fetch":
                from stratum.collectors.direct_fetch import fetch_source
                results = fetch_source(source, run_date, raise_on_error=True)

            elif access == "rss":
                from stratum.collectors.rss import fetch_feed
                locale = source.get("locale", "en")
                category = source.get("category", "media")
                urls = source.get("urls", [])
                timeout = source.get("timeout", 15)

                results = []
                for url in urls:
                    try:
                        results += fetch_feed(
                            url,
                            keywords,
                            sid,
                            locale,
                            category,
                            timeout,
                            raise_on_error=True,
                        )
                    except Exception as url_error:
                        warning = "; ".join(
                            value for value in [warning, f"{url}: {url_error}"] if value
                        )
                if warning and not results:
                    raise RuntimeError(warning)

            elif access == "browser":
                from stratum.collectors.browser import fetch_source
                results = fetch_source(source, run_date)

            else:
                print(f"  ⚠️  Unknown access type '{access}' for [{sid}]", file=sys.stderr)
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                source_stats.append(CollectorSourceStats(
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
            source_stats.append(CollectorSourceStats(
                source=sid,
                access=access,
                status="ok" if results else "empty",
                hits=len(results),
                duration_ms=elapsed,
                locale=locale,
                category=category,
                dated=dated,
                error=warning,
            ))

        except Exception as e:
            fallback_access = source.get("fallback_access")
            if e.__class__.__name__ == "BrowserCollectorUnavailable" and fallback_access == "direct_fetch":
                try:
                    print(
                        f"  ⚠️  [browser] {sid} unavailable; trying direct_fetch fallback",
                        file=sys.stderr,
                    )
                    from stratum.collectors.direct_fetch import fetch_source

                    fallback_source = dict(source)
                    fallback_source["access"] = "direct_fetch"
                    results = fetch_source(
                        fallback_source,
                        run_date,
                        raise_on_error=True,
                    )
                    all_results.extend(results)
                    elapsed = round((time.perf_counter() - started) * 1000, 1)
                    dated = sum(1 for r in results if getattr(r, "published_at", None))
                    source_stats.append(CollectorSourceStats(
                        source=sid,
                        access=access or "unknown",
                        status="ok" if results else "empty",
                        hits=len(results),
                        duration_ms=elapsed,
                        locale=locale,
                        category=category,
                        dated=dated,
                        error=f"browser unavailable; direct_fetch fallback: {e}",
                    ))
                    continue
                except Exception as fallback_error:
                    e = fallback_error

            print(f"  ⚠️  [{access}] {sid} error: {e}", file=sys.stderr)
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            status = (
                "unsupported"
                if e.__class__.__name__ == "BrowserCollectorUnavailable"
                else "error"
            )
            source_stats.append(CollectorSourceStats(
                source=sid,
                access=access or "unknown",
                status=status,
                hits=0,
                duration_ms=elapsed,
                locale=locale,
                category=category,
                error=str(e),
            ))

    return CollectorRun(results=all_results, source_stats=source_stats)
