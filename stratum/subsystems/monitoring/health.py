"""Health Tracker — Per-channel source health statistics.

Deterministic core: daily record writing, stats aggregation, dry streak detection.
NDJSON append-only for durability. Query tool for CLI inspection.
"""

import json
import os
from collections import defaultdict
from datetime import date
from typing import Optional


def ensure_channel_dir(health_data_dir: str, channel: str) -> str:
    """Create channel data directory if missing. Returns path."""
    path = os.path.join(health_data_dir, channel)
    os.makedirs(path, exist_ok=True)
    return path


def write_daily_record(
    channel_dir: str,
    run_date: str,
    source: str,
    hits: int = 0,
    selected: int = 0,
    rejected: int = 0,
    scanned: bool = True,
    http_code: int = 200,
    tags: list[str] = None,
):
    """Append one line to source-daily.ndjson."""
    record = {
        "date": run_date,
        "source": source,
        "scanned": scanned,
        "hits": hits,
        "selected": selected,
        "rejected": rejected,
        "http_code": http_code,
        "tags": tags or [],
    }
    path = os.path.join(channel_dir, "source-daily.ndjson")
    with open(path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_daily_records(channel_dir: str) -> list[dict]:
    """Load all daily records for a channel."""
    path = os.path.join(channel_dir, "source-daily.ndjson")
    if not os.path.exists(path):
        return []
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def rebuild_stats(channel_dir: str) -> dict:
    """Aggregate all daily records into per-source statistics."""
    records = load_daily_records(channel_dir)

    by_source = defaultdict(lambda: {
        "source": "",
        "total_scans": 0,
        "total_hits": 0,
        "total_selected": 0,
        "total_rejected": 0,
        "dry_streak": 0,
        "first_seen": None,
        "last_seen": None,
        "hit_rate": 0.0,
        "http_errors": 0,
    })

    for r in records:
        src = r["source"]
        stats = by_source[src]
        stats["source"] = src
        stats["total_scans"] += 1
        stats["total_hits"] += r.get("hits", 0)
        stats["total_selected"] += r.get("selected", 0)
        stats["total_rejected"] += r.get("rejected", 0)

        if r.get("http_code", 200) >= 400:
            stats["http_errors"] += 1

        if r.get("hits", 0) > 0:
            stats["dry_streak"] = 0
        else:
            stats["dry_streak"] += 1

        if stats["first_seen"] is None or r["date"] < stats["first_seen"]:
            stats["first_seen"] = r["date"]
        if stats["last_seen"] is None or r["date"] > stats["last_seen"]:
            stats["last_seen"] = r["date"]

    # Compute hit rates
    for stats in by_source.values():
        if stats["total_scans"] > 0:
            stats["hit_rate"] = round(stats["total_hits"] / stats["total_scans"], 3)

    # Write stats
    result = {"sources": dict(by_source), "total_sources": len(by_source),
              "updated": date.today().isoformat()}

    path = os.path.join(channel_dir, "source-stats.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


def get_dry_sources(channel_dir: str, min_dry_days: int = 3) -> list[dict]:
    """Find sources with dry streak exceeding threshold."""
    stats = rebuild_stats(channel_dir)
    dry = []
    for src, s in stats.get("sources", {}).items():
        if s["dry_streak"] >= min_dry_days:
            dry.append({"source": src, "dry_streak": s["dry_streak"],
                        "hit_rate": s["hit_rate"], "last_seen": s["last_seen"]})
    return sorted(dry, key=lambda x: -x["dry_streak"])


def get_top_contributors(channel_dir: str, limit: int = 10) -> list[dict]:
    """Find top contributing sources by total hits."""
    stats = rebuild_stats(channel_dir)
    sources = list(stats.get("sources", {}).values())
    sources.sort(key=lambda s: -s["total_hits"])
    return [{"source": s["source"], "hits": s["total_hits"],
             "hit_rate": s["hit_rate"]} for s in sources[:limit]]
