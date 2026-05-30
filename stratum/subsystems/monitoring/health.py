"""Health Tracker — Per-channel source health statistics.

Deterministic core: daily record writing, stats aggregation, dry streak detection.
NDJSON append-only for durability. Query tool for CLI inspection.
"""

from __future__ import annotations

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
    duration_ms: float | None = None,
    error: str | None = None,
    metadata: dict | None = None,
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
    if duration_ms is not None:
        record["duration_ms"] = duration_ms
    if error:
        record["error"] = error
    if metadata:
        record["metadata"] = metadata
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


def _latest_record_per_source_date(records: list[dict]) -> list[dict]:
    """Collapse append-only replays so each source contributes once per date."""
    latest: dict[tuple[str, str], dict] = {}
    for record in records:
        source = record.get("source")
        run_date = record.get("date")
        if not source or not run_date:
            continue
        latest[(source, run_date)] = record
    return list(latest.values())


def _record_status(record: dict) -> str:
    """Return a health record status when collector metadata/tags provide one."""
    metadata = record.get("metadata") or {}
    if metadata.get("status"):
        return str(metadata["status"])
    tags = record.get("tags") or []
    if tags:
        return str(tags[-1])
    return ""


def rebuild_stats(channel_dir: str) -> dict:
    """Aggregate all daily records into per-source statistics."""
    records = _latest_record_per_source_date(load_daily_records(channel_dir))

    by_source = defaultdict(lambda: {
        "source": "",
        "total_scans": 0,
        "total_hits": 0,
        "total_selected": 0,
        "total_rejected": 0,
        "dry_streak": 0,
        "selected_dry_streak": 0,
        "first_seen": None,
        "last_seen": None,
        "hit_rate": 0.0,
        "selected_rate": 0.0,
        "http_errors": 0,
        "http_error_streak": 0,
        "total_dated": 0,
        "dated_hits_observed": 0,
        "dated_rate": None,
        "dated_observations": 0,
    })

    records_by_source = defaultdict(list)
    for r in records:
        records_by_source[r["source"]].append(r)

    for src, source_records in records_by_source.items():
        source_records.sort(key=lambda r: r.get("date", ""))
        dry_streak = 0
        selected_dry_streak = 0
        stats = by_source[src]
        stats["source"] = src

        for r in source_records:
            selected = r.get("selected", r.get("hits", 0))
            status = _record_status(r)
            scanned = r.get("scanned", True) and status != "unsupported"
            if scanned:
                stats["total_scans"] += 1
                stats["total_hits"] += r.get("hits", 0)
                stats["total_selected"] += selected
                stats["total_rejected"] += r.get("rejected", 0)

                if _is_error_record(r):
                    stats["http_errors"] += 1
                    stats["http_error_streak"] += 1
                else:
                    stats["http_error_streak"] = 0

                metadata = r.get("metadata") or {}
                dated = metadata.get("dated", r.get("dated"))
                if dated is not None:
                    stats["dated_observations"] += 1
                    stats["dated_hits_observed"] += r.get("hits", 0)
                    stats["total_dated"] += dated

                if r.get("hits", 0) > 0:
                    dry_streak = 0
                else:
                    dry_streak += 1

                if selected > 0:
                    selected_dry_streak = 0
                else:
                    selected_dry_streak += 1

            if stats["first_seen"] is None or r["date"] < stats["first_seen"]:
                stats["first_seen"] = r["date"]
            if stats["last_seen"] is None or r["date"] > stats["last_seen"]:
                stats["last_seen"] = r["date"]

        stats["dry_streak"] = dry_streak
        stats["selected_dry_streak"] = selected_dry_streak

    # Compute hit rates
    for stats in by_source.values():
        if stats["total_scans"] > 0:
            stats["hit_rate"] = round(stats["total_hits"] / stats["total_scans"], 3)
            stats["selected_rate"] = round(stats["total_selected"] / stats["total_scans"], 3)
        if stats["dated_hits_observed"] > 0:
            stats["dated_rate"] = round(stats["total_dated"] / stats["dated_hits_observed"], 3)

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


def get_non_contributing_sources(channel_dir: str, min_days: int = 3) -> list[dict]:
    """Find sources that scanned but contributed no selected records recently."""
    stats = rebuild_stats(channel_dir)
    sources = []
    for src, s in stats.get("sources", {}).items():
        if s["selected_dry_streak"] >= min_days:
            sources.append({
                "source": src,
                "selected_dry_streak": s["selected_dry_streak"],
                "selected_rate": s["selected_rate"],
                "hit_rate": s["hit_rate"],
                "last_seen": s["last_seen"],
            })
    return sorted(sources, key=lambda x: -x["selected_dry_streak"])


def get_source_alerts(
    channel_dir: str,
    *,
    dry_streak_days: int = 3,
    selected_dry_streak_days: int = 3,
    http_error_days: int = 2,
    min_dated_rate: float = 0.5,
    min_scans_for_quality: int = 3,
) -> list[dict]:
    """Return threshold-based source health alerts sorted by severity."""
    stats = rebuild_stats(channel_dir)
    alerts: list[dict] = []

    for source, source_stats in stats.get("sources", {}).items():
        dry_streak = source_stats["dry_streak"]
        if dry_streak >= dry_streak_days:
            alerts.append({
                "source": source,
                "type": "dry_streak",
                "severity": _alert_severity(dry_streak, dry_streak_days),
                "value": dry_streak,
                "threshold": dry_streak_days,
                "last_seen": source_stats["last_seen"],
                "message": f"{source} has no collector/search hits for {dry_streak} scanned days",
            })

        selected_dry_streak = source_stats["selected_dry_streak"]
        if selected_dry_streak >= selected_dry_streak_days:
            alerts.append({
                "source": source,
                "type": "selected_dry_streak",
                "severity": _alert_severity(selected_dry_streak, selected_dry_streak_days),
                "value": selected_dry_streak,
                "threshold": selected_dry_streak_days,
                "selected_rate": source_stats["selected_rate"],
                "last_seen": source_stats["last_seen"],
                "message": f"{source} has contributed no selected records for {selected_dry_streak} scanned days",
            })

        http_error_streak = source_stats["http_error_streak"]
        if http_error_streak >= http_error_days:
            alerts.append({
                "source": source,
                "type": "http_errors",
                "severity": _alert_severity(http_error_streak, http_error_days),
                "value": http_error_streak,
                "threshold": http_error_days,
                "total_errors": source_stats["http_errors"],
                "last_seen": source_stats["last_seen"],
                "message": f"{source} has HTTP errors for {http_error_streak} consecutive scanned days",
            })

        dated_rate = source_stats["dated_rate"]
        if (
            dated_rate is not None
            and source_stats["total_scans"] >= min_scans_for_quality
            and dated_rate < min_dated_rate
        ):
            alerts.append({
                "source": source,
                "type": "low_dated_rate",
                "severity": "warning",
                "value": dated_rate,
                "threshold": min_dated_rate,
                "total_hits": source_stats["total_hits"],
                "total_dated": source_stats["total_dated"],
                "last_seen": source_stats["last_seen"],
                "message": f"{source} has dated metadata on only {dated_rate:.0%} of hit records",
            })

    severity_rank = {"critical": 0, "warning": 1}
    return sorted(
        alerts,
        key=lambda alert: (
            severity_rank.get(alert["severity"], 9),
            alert["source"],
            alert["type"],
        ),
    )


def _alert_severity(value: int, threshold: int) -> str:
    return "critical" if value >= threshold * 2 else "warning"


def _is_error_record(record: dict) -> bool:
    """Return True when a scanned health record represents a source error."""
    if record.get("http_code", 200) >= 400:
        return True
    return _record_status(record) == "error"
