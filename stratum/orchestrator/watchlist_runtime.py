"""Watchlist merge, diagnostics, and health handoff for daily orchestration."""

from __future__ import annotations

import json
import os
import sys

import yaml

from stratum.contracts.pipeline_artifacts import (
    RAW_STATS,
    WATCHLIST_CANDIDATES,
    WATCHLIST_OBSERVATIONS,
    WATCHLIST_RESULTS,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


def run_watchlist(
    domain: str,
    workspace: str,
    run_date: str,
    raw_path: str,
    health_data_dir: str | None = None,
    merge_existing: bool = True,
):
    """Run all watchlists and write/merge results into raw.json."""
    try:
        from stratum.sourcing.watchlist import collect_with_stats
        from stratum.sourcing.discovery import canonicalize_url

        watchlist_run = collect_with_stats(
            domain,
            workspace,
            run_date,
            source_health=load_watchlist_source_health(domain, health_data_dir),
        )
        watchlist_results = watchlist_run.results
        stats_path = os.path.join(os.path.dirname(raw_path), "watchlist_stats.json")
        observations_path = os.path.join(os.path.dirname(raw_path), WATCHLIST_OBSERVATIONS.filename)
        results_path = os.path.join(os.path.dirname(raw_path), WATCHLIST_RESULTS.filename)
        candidates_path = os.path.join(os.path.dirname(raw_path), WATCHLIST_CANDIDATES.filename)
        _write_jsonl(observations_path, getattr(watchlist_run, "observations", []))
        _write_watchlist_results(results_path, watchlist_results, canonicalize_url)
        _write_jsonl(candidates_path, getattr(watchlist_run, "candidates", []))
        if not watchlist_results:
            set_watchlist_selected_counts(watchlist_run.source_stats, {})
            _write_watchlist_stats(stats_path, watchlist_run, domain, run_date)
            write_watchlist_health(domain, run_date, watchlist_run.source_stats, health_data_dir)
            if not merge_existing:
                with open(raw_path, "w") as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
            return {"status": "empty", "output": stats_path, "detail": "no watchlist results"}

        search_results = load_raw_results(raw_path) if merge_existing and os.path.exists(raw_path) else []
        merged, selected_by_source = _merge_watchlist_and_discovery_results(
            watchlist_results,
            search_results,
            canonicalize_url,
        )
        with open(raw_path, "w") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

        set_watchlist_selected_counts(watchlist_run.source_stats, selected_by_source)
        _write_watchlist_stats(stats_path, watchlist_run, domain, run_date)
        write_watchlist_health(domain, run_date, watchlist_run.source_stats, health_data_dir)
        update_post_collect_search_stats(raw_path, merged)

        added = len(watchlist_results)
        print(f"\n📡 Watchlist: +{added} direct-fetch → {len(merged)} total in raw.json",
              file=sys.stderr)
        return {"status": "success", "output": stats_path, "detail": f"{added} collected; {len(merged)} total"}
    except Exception as exc:
        print(f"⚠️  Watchlist skipped: {exc}", file=sys.stderr)
        return {"status": "failed_nonblocking", "output": raw_path, "detail": str(exc)}


def _merge_watchlist_and_discovery_results(watchlist_results, search_results, canonicalize_url):
    seen_urls = set()
    merged = []
    selected_by_source = {}
    for result in watchlist_results:
        item = result.to_dict() if hasattr(result, "to_dict") else result
        url = item.get("url", "")
        canonical = item.get("canonical_url") or canonicalize_url(url)
        if url and canonical not in seen_urls:
            item["canonical_url"] = canonical
            seen_urls.add(canonical)
            merged.append(item)
            source_id = watchlist_source_id(item)
            if source_id:
                selected_by_source[source_id] = selected_by_source.get(source_id, 0) + 1
    for result in search_results:
        url = result.get("url", "")
        canonical = result.get("canonical_url") or canonicalize_url(url)
        if url and canonical not in seen_urls:
            result["canonical_url"] = canonical
            seen_urls.add(canonical)
            merged.append(result)
    return merged, selected_by_source


def _write_watchlist_results(results_path: str, watchlist_results: list, canonicalize_url) -> None:
    """Persist the unmerged watchlist result set for reuse and audit."""
    rows = []
    for result in watchlist_results:
        item = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        url = item.get("url", "")
        item["canonical_url"] = item.get("canonical_url") or canonicalize_url(url)
        rows.append(item)
    with open(results_path, "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def _write_jsonl(path: str, rows: list[dict]) -> None:
    """Write JSONL audit records, including empty files for empty runs."""
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def update_post_collect_search_stats(raw_path: str, merged_results: list[dict]) -> None:
    """Annotate raw.stats.json with final raw.json coverage after watchlists merge."""
    stats_path = os.path.join(os.path.dirname(raw_path), RAW_STATS.filename)
    if not os.path.exists(stats_path):
        return
    try:
        with open(stats_path) as f:
            stats = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    by_type: dict[str, int] = {}
    by_locale: dict[str, int] = {}
    for result in merged_results:
        source_type = str(result.get("source_type_hint") or "unknown")
        locale = str(result.get("locale") or "unknown")
        by_type[source_type] = by_type.get(source_type, 0) + 1
        by_locale[locale] = by_locale.get(locale, 0) + 1

    final_gaps = []
    for source_type, minimum in sorted(_source_type_minimums().items()):
        available = by_type.get(source_type, 0)
        if available < int(minimum):
            final_gaps.append({
                "source_type": source_type,
                "minimum": int(minimum),
                "raw_available": available,
                "shortfall": int(minimum) - available,
            })

    diagnostics = stats.setdefault("diagnostics", {})
    diagnostics["post_collect_total_raw"] = len(merged_results)
    diagnostics["post_collect_by_source_type"] = by_type
    diagnostics["post_collect_by_locale"] = by_locale
    diagnostics["post_collect_source_type_gaps"] = final_gaps
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def _source_type_minimums() -> dict:
    try:
        config_path = os.environ.get("STRATUM_CONFIG_PATH") or CONFIG_PATH
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("curation", {}).get("min_per_source_type", {}) or {}
    except Exception:
        return {}
    return {}


def load_raw_results(raw_path: str) -> list[dict]:
    """Read raw.json as a result list for final diagnostics."""
    try:
        with open(raw_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get("results", [])
        return results if isinstance(results, list) else []
    return []


def set_watchlist_selected_counts(source_stats: list, selected_by_source: dict[str, int]) -> None:
    """Attach post-merge selected counts to mutable watchlist stats."""
    for stat in source_stats:
        if hasattr(stat, "source"):
            stat.selected = int(selected_by_source.get(stat.source, 0) or 0)
        else:
            stat["selected"] = int(selected_by_source.get(stat.get("source", ""), 0) or 0)


def watchlist_source_id(result: dict) -> str:
    """Return the watchlist source id from a raw SearchResult dict."""
    engine = str(result.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]

    query_id = str(result.get("query_id") or "")
    for prefix in ("df-", "rss-", "b-"):
        if query_id.startswith(prefix):
            query_id = query_id[len(prefix):]
            break
    if query_id.endswith("-fallback"):
        query_id = query_id[:-len("-fallback")]
    if query_id.endswith("-list"):
        query_id = query_id[:-len("-list")]
    return query_id


def write_watchlist_health(
    domain: str,
    run_date: str,
    source_stats: list,
    health_data_dir: str | None,
) -> None:
    """Append watchlist source health records to monitoring NDJSON."""
    if not health_data_dir or not source_stats:
        return
    try:
        from stratum.subsystems.monitoring import ensure_channel_dir, write_daily_record

        channel_dir = ensure_channel_dir(health_data_dir, domain)
        for stat in source_stats:
            data = stat.to_dict() if hasattr(stat, "to_dict") else dict(stat)
            status = data.get("status", "")
            write_daily_record(
                channel_dir=channel_dir,
                run_date=run_date,
                source=data.get("source", "unknown"),
                hits=int(data.get("hits", 0) or 0),
                selected=int(data.get("selected", 0) or 0),
                scanned=status != "unsupported",
                http_code=200 if status in {"ok", "empty"} else 500,
                tags=["watchlist", data.get("access", "unknown"), status],
                duration_ms=data.get("duration_ms"),
                error=data.get("error") or None,
                metadata={
                    "locale": data.get("locale", ""),
                    "category": data.get("category", ""),
                    "dated": data.get("dated", 0),
                    "status": status,
                },
            )
    except Exception as exc:
        print(f"⚠️  Watchlist health write skipped: {exc}", file=sys.stderr)


def load_watchlist_source_health(domain: str, health_data_dir: str | None) -> dict[str, dict]:
    """Load prior watchlist source health for acquisition priority scoring."""
    if not health_data_dir:
        return {}
    try:
        from stratum.subsystems.monitoring import ensure_channel_dir, rebuild_stats

        channel_dir = ensure_channel_dir(health_data_dir, domain)
        return rebuild_stats(channel_dir).get("sources", {})
    except Exception as exc:
        print(f"⚠️  Watchlist health load skipped: {exc}", file=sys.stderr)
        return {}


def _write_watchlist_stats(stats_path: str, watchlist_run, domain: str, run_date: str) -> None:
    with open(stats_path, "w") as f:
        json.dump(watchlist_run.stats_json(domain, run_date), f, ensure_ascii=False, indent=2)


# Backward-compatible function names for older tests, scripts, and imports.
run_collector = run_watchlist
_merge_collector_and_search_results = _merge_watchlist_and_discovery_results
set_collector_selected_counts = set_watchlist_selected_counts
collector_source_id = watchlist_source_id
write_collector_health = write_watchlist_health
load_collector_source_health = load_watchlist_source_health
_write_collector_stats = _write_watchlist_stats
