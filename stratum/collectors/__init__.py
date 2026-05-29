"""Collectors — content acquisition beyond search engines.

Single entry point: collect(domain, workspace, run_date).
Dispatches by source.access to the right strategy module.

Strategy modules:
  direct_fetch  — HTTP GET → HTML parse (heading-first + read-more fallback)
  rss           — HTTP GET → XML parse (RSS 2.0 + Atom)
  browser       — headless Chrome (future)

All strategies return list[SearchResult]. The orchestrator merges and
returns the combined pool. Pipeline only knows about collect().
"""

import sys
from typing import Any

from stratum.collectors.keywords import load_keywords
from stratum.collectors.registry import get_active_sources
from stratum.subsystems.search.models import SearchResult


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Collect articles from ALL active sources across all access types.

    Reads source_registry from domain.yaml, dispatches by access type,
    and returns merged SearchResult list.

    Pipeline contract: collect() is the ONLY function pipeline calls.
    Adding a new access type = add strategy module + register here.
    Pipeline code never changes.
    """
    sources = get_active_sources(domain, workspace)
    if not sources:
        return []

    keywords = load_keywords(domain, workspace)

    all_results: list[SearchResult] = []

    for source in sources:
        access = source.get("access", "")
        sid = source.get("id", "?")

        try:
            if access == "direct_fetch":
                from stratum.collectors.direct_fetch import fetch_source
                results = fetch_source(source, run_date)

            elif access == "rss":
                from stratum.collectors.rss import fetch_feed
                locale = source.get("locale", "en")
                category = source.get("category", "media")
                urls = source.get("urls", [])
                timeout = source.get("timeout", 15)

                results = []
                for url in urls:
                    results += fetch_feed(url, keywords, sid, locale, category, timeout)

            # elif access == "browser":  # future
            #     results = []

            else:
                print(f"  ⚠️  Unknown access type '{access}' for [{sid}]", file=sys.stderr)
                continue

            if results:
                print(f"  ✅ [{access}] {sid}: {len(results)} articles", file=sys.stderr)
            else:
                print(f"  ⚠️  [{access}] {sid}: no articles", file=sys.stderr)

            all_results.extend(results)

        except Exception as e:
            print(f"  ⚠️  [{access}] {sid} error: {e}", file=sys.stderr)

    return all_results
