"""Discovery observations emitted before curation scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def observed_at() -> str:
    """Return an ISO timestamp for discovery observation records."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def observation_from_result(result, query_by_id: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a pre-curation discovery observation from a SearchResult."""
    query_by_id = query_by_id or {}
    query = query_by_id.get(getattr(result, "query_id", ""))
    url = getattr(result, "url", "")
    source_domain = getattr(result, "source_domain", "") or _domain(url)
    row = {
        "source": getattr(result, "engine", "") or "discovery",
        "access": "discovery",
        "url": url,
        "title": getattr(result, "title", ""),
        "snippet": getattr(result, "snippet", ""),
        "published_at": getattr(result, "published_at", None),
        "locale": getattr(result, "locale", ""),
        "source_domain": source_domain,
        "source_type_hint": getattr(result, "source_type_hint", ""),
        "engine": getattr(result, "engine", ""),
        "query_id": getattr(result, "query_id", ""),
        "query_used": getattr(query, "text", ""),
        "query_dimension": getattr(result, "query_dimension", ""),
        "observed_at": observed_at(),
    }
    return row


def observations_from_results(results: list, queries: list[Any]) -> list[dict[str, Any]]:
    """Build discovery observations for normalized provider results."""
    query_by_id = {getattr(query, "id", ""): query for query in queries}
    return [observation_from_result(result, query_by_id) for result in results]


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        return host[4:]
    if host.startswith("m."):
        return host[2:]
    return host
