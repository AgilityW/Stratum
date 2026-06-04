"""Observation-layer helpers for SourceTrace inputs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


WATCHLIST_OBSERVATIONS = "watchlist_observations.jsonl"
DISCOVERY_OBSERVATIONS = "discovery_observations.jsonl"


def summarize_observations(
    watchlist_observations: list[dict[str, Any]] | None = None,
    discovery_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize pre-admission and pre-curation observation records."""
    watchlist_observations = watchlist_observations or []
    discovery_observations = discovery_observations or []
    return {
        "watchlist": _summarize_layer(watchlist_observations, default_layer="watchlist"),
        "discovery": _summarize_layer(discovery_observations, default_layer="discovery"),
        "totals": {
            "observations": len(watchlist_observations) + len(discovery_observations),
            "watchlist_observations": len(watchlist_observations),
            "discovery_observations": len(discovery_observations),
        },
    }


def observation_to_candidate_key(record: dict[str, Any]) -> dict[str, str]:
    """Return stable join keys used to compare observations with candidates."""
    return {
        "source": _source(record),
        "url": str(record.get("url") or ""),
        "title": str(record.get("title") or ""),
        "engine": str(record.get("engine") or ""),
    }


def _summarize_layer(records: list[dict[str, Any]], *, default_layer: str) -> dict[str, Any]:
    by_source: dict[str, int] = defaultdict(int)
    by_access: dict[str, int] = defaultdict(int)
    dated = 0
    for record in records:
        by_source[_source(record)] += 1
        by_access[str(record.get("access") or record.get("engine") or default_layer)] += 1
        if record.get("published_at") or record.get("datePublished") or record.get("date"):
            dated += 1
    return {
        "total": len(records),
        "dated": dated,
        "dated_rate": round(dated / max(len(records), 1), 4),
        "by_source": dict(sorted(by_source.items())),
        "by_access": dict(sorted(by_access.items())),
    }


def _source(record: dict[str, Any]) -> str:
    source = str(record.get("source") or "")
    if source:
        return source
    engine = str(record.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    return str(record.get("source_domain") or "unknown")
