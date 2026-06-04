"""Canonical URL provenance and dedupe-loss analysis."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def build_provenance(
    watchlist_results: list[dict[str, Any]],
    raw_results: list[dict[str, Any]],
    *,
    discovery_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Group acquisition paths by canonical URL and mark final consumption."""
    discovery_candidates = discovery_candidates or []
    groups: dict[str, dict[str, Any]] = defaultdict(_empty_group)

    for item in watchlist_results:
        _add_path(groups, item, "watchlist")
    for item in discovery_candidates:
        _add_path(groups, item, "discovery_candidate")
    for item in raw_results:
        canonical = _canonical(item)
        group = groups[canonical]
        group["canonical_url"] = canonical
        group["consumed"] = True
        group["raw_title"] = item.get("title", "")
        _add_path(groups, item, "raw")

    rows = []
    for canonical, group in groups.items():
        paths = group["paths"]
        group["path_count"] = len(paths)
        group["engines"] = sorted({path.get("engine", "") for path in paths if path.get("engine")})
        group["sources"] = sorted({path.get("source", "") for path in paths if path.get("source")})
        group["deduped_paths"] = max(0, len(paths) - 1)
        group["canonical_url"] = canonical
        rows.append(group)

    return {
        "items": sorted(rows, key=lambda item: (-item["path_count"], item["canonical_url"])),
        "totals": {
            "canonical_urls": len(rows),
            "multi_path_urls": sum(1 for row in rows if row["path_count"] > 1),
            "deduped_paths": sum(row["deduped_paths"] for row in rows),
        },
    }


def _empty_group() -> dict[str, Any]:
    return {
        "canonical_url": "",
        "consumed": False,
        "raw_title": "",
        "paths": [],
    }


def _add_path(groups: dict[str, dict[str, Any]], item: dict[str, Any], layer: str) -> None:
    canonical = _canonical(item)
    if not canonical:
        return
    group = groups[canonical]
    group["canonical_url"] = canonical
    group["paths"].append({
        "layer": layer,
        "source": item.get("source") or _source_from_engine(item.get("engine", "")),
        "engine": item.get("engine", ""),
        "status": item.get("status", ""),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
    })


def _source_from_engine(engine: str) -> str:
    engine = str(engine or "")
    return engine.split(":", 1)[1] if ":" in engine else engine


def _canonical(item: dict[str, Any]) -> str:
    value = str(item.get("canonical_url") or item.get("url") or "")
    if not value:
        return ""
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    query = urlencode([
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ])
    return urlunparse((parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/", "", query, ""))
