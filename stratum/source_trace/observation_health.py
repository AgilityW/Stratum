"""Observation health diagnostics for parser and provider layers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


BOILERPLATE_TITLES = {
    "read more",
    "learn more",
    "read article",
    "newsroom",
    "press releases",
    "click here",
}


def assess_observation_health(
    watchlist_observations: list[dict[str, Any]],
    discovery_observations: list[dict[str, Any]],
    *,
    watchlist_candidates: list[dict[str, Any]] | None = None,
    discovery_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess observation coverage, date quality, title quality, and conversion."""
    watchlist_candidates = watchlist_candidates or []
    discovery_candidates = discovery_candidates or []
    return {
        "watchlist": _layer_health(watchlist_observations, watchlist_candidates),
        "discovery": _layer_health(discovery_observations, discovery_candidates),
    }


def _layer_health(observations: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, dict[str, Any]] = defaultdict(_row)
    candidate_keys = {_key(candidate) for candidate in candidates}
    seen_keys: set[tuple[str, str]] = set()

    for observation in observations:
        source = _source(observation)
        row = by_source[source]
        row["source"] = source
        row["observations"] += 1
        key = _key(observation)
        if key in seen_keys:
            row["duplicates"] += 1
        seen_keys.add(key)
        if key in candidate_keys:
            row["converted_to_candidate"] += 1
        if _dated(observation):
            row["dated"] += 1
        if _boilerplate_title(observation):
            row["boilerplate_titles"] += 1

    rows = []
    for row in by_source.values():
        total = max(row["observations"], 1)
        row["dated_rate"] = round(row["dated"] / total, 4)
        row["candidate_conversion_rate"] = round(row["converted_to_candidate"] / total, 4)
        row["duplicate_rate"] = round(row["duplicates"] / total, 4)
        row["boilerplate_rate"] = round(row["boilerplate_titles"] / total, 4)
        row["health_status"] = _health_status(row)
        rows.append(row)
    return {
        "sources": sorted(rows, key=lambda item: (item["health_status"], item["source"])),
        "totals": {
            "observations": len(observations),
            "candidates": len(candidates),
            "source_count": len(rows),
        },
    }


def _row() -> dict[str, Any]:
    return {
        "source": "",
        "observations": 0,
        "converted_to_candidate": 0,
        "dated": 0,
        "duplicates": 0,
        "boilerplate_titles": 0,
    }


def _health_status(row: dict[str, Any]) -> str:
    if row["observations"] == 0:
        return "empty"
    if row["boilerplate_rate"] >= 0.5 or row["candidate_conversion_rate"] == 0:
        return "needs_adapter_review"
    if row["dated_rate"] < 0.25:
        return "date_poor"
    if row["duplicate_rate"] > 0.5:
        return "duplicate_heavy"
    return "ok"


def _key(record: dict[str, Any]) -> tuple[str, str]:
    return (_source(record), str(record.get("canonical_url") or record.get("url") or record.get("title") or ""))


def _source(record: dict[str, Any]) -> str:
    return str(record.get("source") or record.get("source_domain") or record.get("engine") or "unknown")


def _dated(record: dict[str, Any]) -> bool:
    return bool(record.get("published_at") or record.get("datePublished") or record.get("date"))


def _boilerplate_title(record: dict[str, Any]) -> bool:
    title = str(record.get("title") or "").strip().lower()
    return title in BOILERPLATE_TITLES or len(title) < 10
