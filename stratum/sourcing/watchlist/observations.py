"""Watchlist observation records emitted before admission scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def observed_at() -> str:
    """Return an ISO timestamp for observation audit records."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def observation_record(
    *,
    source: str,
    access: str,
    url: str,
    title: str,
    snippet: str = "",
    published_at: str | None = None,
    locale: str = "",
    source_domain: str = "",
    source_type_hint: str = "",
    engine: str = "",
    query_id: str = "",
    parser: str = "",
    source_url: str = "",
    observed_at_value: str | None = None,
) -> dict[str, Any]:
    """Build a minimal pre-admission structured observation."""
    row = {
        "source": source,
        "access": access,
        "url": url,
        "title": title,
        "snippet": snippet,
        "published_at": published_at,
        "locale": locale,
        "source_domain": source_domain,
        "source_type_hint": source_type_hint,
        "engine": engine,
        "query_id": query_id,
    }
    if parser:
        row["parser"] = parser
    row["observed_at"] = observed_at_value or observed_at()
    if source_url:
        row["source_url"] = source_url
    return row


def observation_from_result(
    result,
    *,
    source: str,
    access: str,
    parser: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    """Build an observation from a SearchResult-like parser output."""
    return observation_record(
        source=source,
        access=access,
        url=getattr(result, "url", ""),
        title=getattr(result, "title", ""),
        snippet=getattr(result, "snippet", ""),
        published_at=getattr(result, "published_at", None),
        locale=getattr(result, "locale", ""),
        source_domain=getattr(result, "source_domain", ""),
        source_type_hint=getattr(result, "source_type_hint", ""),
        engine=getattr(result, "engine", ""),
        query_id=getattr(result, "query_id", ""),
        parser=parser,
        source_url=source_url,
    )
