"""Fixed URL acquisition channel orchestration."""

from __future__ import annotations

import sys

from stratum.sourcing.watchlist.models import WatchlistChannelResult


def _fetch_with_optional_keywords(
    fetch_source,
    source: dict,
    run_date: str,
    keywords: list[str] | None,
    observation_sink: list[dict] | None = None,
    candidate_sink: list[dict] | None = None,
    **kwargs,
):
    try:
        return fetch_source(
            source,
            run_date,
            keywords=keywords,
            observation_sink=observation_sink,
            candidate_sink=candidate_sink,
            **kwargs,
        )
    except TypeError as exc:
        if "keyword" not in str(exc) and "candidate_sink" not in str(exc) and "observation_sink" not in str(exc):
            raise
        try:
            return fetch_source(source, run_date, keywords=keywords, **kwargs)
        except TypeError as second_exc:
            if "keyword" not in str(second_exc):
                raise
            return fetch_source(source, run_date, **kwargs)


def collect_source(source: dict, run_date: str, keywords: list[str] | None = None) -> WatchlistChannelResult:
    """Collect one configured fixed-URL source.

    The URL channel includes static HTTP fetches and browser-rendered fetches
    because both start from trusted source-owned URLs instead of broad Search.
    """
    access = source.get("access", "")
    locale = source.get("locale", "")
    category = source.get("category", "")
    observations: list[dict] = []
    candidates: list[dict] = []

    if access == "direct_fetch":
        from stratum.sourcing.watchlist.direct_fetch import fetch_source

        results = _fetch_with_optional_keywords(
            fetch_source,
            source,
            run_date,
            keywords,
            observations,
            candidates,
            raise_on_error=True,
        )
        return WatchlistChannelResult(
            results=results,
            access=access,
            status="ok" if results else "empty",
            locale=locale,
            category=category,
            observations=observations,
            candidates=candidates,
        )

    if access == "browser":
        try:
            from stratum.sourcing.watchlist.browser import fetch_source

            results = _fetch_with_optional_keywords(fetch_source, source, run_date, keywords, observations, candidates)
            return WatchlistChannelResult(
                results=results,
                access=access,
                status="ok" if results else "empty",
                locale=locale,
                category=category,
                observations=observations,
                candidates=candidates,
            )
        except Exception as exc:
            if exc.__class__.__name__ != "BrowserWatchlistUnavailable":
                raise
            if source.get("fallback_access") != "direct_fetch":
                raise
            return _direct_fetch_fallback(source, run_date, exc, keywords=keywords)

    raise ValueError(f"unknown URL channel access: {access}")


def _direct_fetch_fallback(
    source: dict,
    run_date: str,
    browser_error: Exception,
    keywords: list[str] | None = None,
) -> WatchlistChannelResult:
    sid = source.get("id", "?")
    print(
        f"  ⚠️  [browser] {sid} unavailable; trying direct_fetch fallback",
        file=sys.stderr,
    )
    from stratum.sourcing.watchlist.direct_fetch import fetch_source

    fallback_source = dict(source)
    fallback_source["access"] = "direct_fetch"
    observations: list[dict] = []
    candidates: list[dict] = []
    results = _fetch_with_optional_keywords(
        fetch_source,
        fallback_source,
        run_date,
        keywords,
        observations,
        candidates,
        raise_on_error=True,
    )
    return WatchlistChannelResult(
        results=results,
        access="browser",
        status="ok" if results else "empty",
        locale=source.get("locale", ""),
        category=source.get("category", ""),
        error=f"browser unavailable; direct_fetch fallback: {browser_error}",
        observations=observations,
        candidates=candidates,
    )
