"""RSS acquisition channel orchestration."""

from __future__ import annotations

from stratum.sourcing.watchlist.models import WatchlistChannelResult


def collect_source(source: dict, keywords: list[str]) -> WatchlistChannelResult:
    """Collect one RSS source, isolating failures per feed URL."""
    from stratum.sourcing.watchlist.rss import fetch_feed

    sid = source.get("id", "?")
    locale = source.get("locale", "en")
    category = source.get("category", "media")
    urls = source.get("urls", [])
    timeout = source.get("timeout", 15)

    results = []
    observations = []
    candidates = []
    warning = ""
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
                observation_sink=observations,
                candidate_sink=candidates,
            )
        except Exception as url_error:
            warning = "; ".join(
                value for value in [warning, f"{url}: {url_error}"] if value
            )

    if warning and not results:
        raise RuntimeError(warning)

    return WatchlistChannelResult(
        results=results,
        access="rss",
        status="ok" if results else "empty",
        locale=locale,
        category=category,
        error=warning,
        observations=observations,
        candidates=candidates,
    )
