"""Daily pipeline SQLite ingest orchestration."""

from __future__ import annotations

import json
import os
import sys

from stratum.db.persistence import foundation_schema_ready as db_foundation_ready
from stratum.orchestrator.db_foundation import (
    build_report_bundle,
    event_article_links_from_threads,
    event_threads_path_for,
    file_sha256,
    load_json_list,
    load_json_object,
    load_jsonl,
    report_artifacts,
    try_db_foundation_ingest,
)

def try_ingest_search_stats(domain_id: str, stats_path: str, run_date: str) -> int:
    """Ingest acquisition query stats sidecar into SQLite query counters."""
    if not os.path.exists(stats_path):
        return 0
    try:
        from stratum.db.ingest import update_query_stats

        with open(stats_path) as f:
            data = json.load(f)
        queries = data.get("queries", []) if isinstance(data, dict) else []
        diagnostics = data.get("diagnostics", {}) if isinstance(data, dict) else {}
        engine_health = diagnostics.get("engine_health") if isinstance(diagnostics, dict) else None
        count = update_query_stats(
            domain_id,
            queries,
            run_date=run_date,
            engine_health=engine_health,
        )
        print(f"💾 DB: {count} search query stats updated", file=sys.stderr)
        return count
    except Exception as exc:
        print(f"⚠️  Acquisition query stats ingest skipped: {exc}", file=sys.stderr)
        return 0


def try_db_ingest(
    domain_id: str,
    run_date: str,
    paths: dict,
    db_dir: str,
    ingest_events: bool = True,
    ingest_entities: bool = True,
    watch_locales: list[str] | None = None,
) -> dict:
    """Ingest pipeline outputs into SQLite database."""
    db_path = os.path.join(db_dir, domain_id, f"{domain_id}.db")
    if not os.path.exists(db_path):
        return {"status": "skipped", "output": db_path, "detail": "database not found"}

    try:
        os.environ["STRATUM_DB_DIR"] = db_dir
        from stratum.db.ingest import (
            ingest_daily_events,
            ingest_entity_snapshots,
            update_entities_after_run,
            upsert_watch_queries,
        )

        event_stats = _ingest_events(
            domain_id,
            run_date,
            paths,
            ingest_events,
            watch_locales or ["en"],
            ingest_daily_events,
            upsert_watch_queries,
        )
        entity_updates, snapshots = _ingest_entities(
            domain_id,
            run_date,
            paths,
            ingest_entities,
            update_entities_after_run,
            ingest_entity_snapshots,
        )
        foundation_stats = try_db_foundation_ingest(domain_id, run_date, paths)
        status = "failed_nonblocking" if event_stats and event_stats.get("errors") else "success"
        if foundation_stats.get("status") == "failed_nonblocking":
            status = "failed_nonblocking"
        return {
            "status": status,
            "output": db_path,
            "detail": _db_ingest_detail(
                ingest_events,
                ingest_entities,
                entity_updates,
                snapshots,
                event_stats,
                foundation_stats,
            ),
        }
    except Exception as exc:
        print(f"⚠️  DB ingestion skipped: {exc}", file=sys.stderr)
        return {"status": "failed_nonblocking", "output": db_path, "detail": str(exc)}


def _ingest_events(
    domain_id: str,
    run_date: str,
    paths: dict,
    ingest_events: bool,
    watch_locales: list[str],
    ingest_daily_events,
    upsert_watch_queries,
) -> dict | None:
    if not ingest_events:
        return None
    event_threads_path = event_threads_path_for(paths)
    if not os.path.exists(event_threads_path):
        return None
    event_stats = ingest_daily_events(event_threads_path, domain_id, run_date)
    if event_stats["errors"]:
        print(f"\n⚠️  DB ingestion errors: {event_stats['errors']}", file=sys.stderr)
    if any(event_stats[key] for key in ["events", "causal_edges", "judgments", "new_threads"]):
        print(f"\n💾 DB: {event_stats['events']} events, {event_stats['causal_edges']} edges, "
              f"{event_stats['judgments']} judgments, {event_stats['new_threads']} new threads",
              file=sys.stderr)
    watch_query_count = persist_event_watch_queries(
        domain_id,
        event_threads_path,
        watch_locales,
        upsert_watch_queries,
        run_date,
    )
    event_stats["watch_queries"] = watch_query_count
    if watch_query_count:
        print(f"💾 DB: {watch_query_count} watch queries upserted", file=sys.stderr)
    return event_stats


def _ingest_entities(
    domain_id: str,
    run_date: str,
    paths: dict,
    ingest_entities: bool,
    update_entities_after_run,
    ingest_entity_snapshots,
) -> tuple[int, int]:
    entity_counts = {}
    entity_updates = 0
    snapshots = 0
    if not ingest_entities:
        return entity_updates, snapshots
    articles_path = paths.get("articles", "")
    if os.path.exists(articles_path):
        with open(articles_path) as f:
            for line in f:
                if not line.strip():
                    continue
                article = json.loads(line)
                for entity_id in article.get("entity_ids", article.get("entities", [])):
                    entity_counts[entity_id] = entity_counts.get(entity_id, 0) + 1
        if entity_counts:
            stats_list = [
                {"id": entity_id, "article_count_today": count}
                for entity_id, count in entity_counts.items()
            ]
            entity_updates = update_entities_after_run(
                domain_id,
                stats_list,
                run_date=run_date,
                scale="daily",
            )
            print(f"💾 DB: {entity_updates} entities updated", file=sys.stderr)
    snapshots = ingest_entity_snapshots(domain_id, "daily", run_date, entity_counts)
    print(f"💾 DB: {snapshots} entity snapshots", file=sys.stderr)
    return entity_updates, snapshots


def _db_ingest_detail(
    ingest_events: bool,
    ingest_entities: bool,
    entity_updates: int,
    snapshots: int,
    event_stats: dict | None,
    foundation_stats: dict,
) -> str:
    details = [
        f"events={'on' if ingest_events else 'off'}",
        f"entities={'on' if ingest_entities else 'off'}",
        f"entity_updates={entity_updates}",
        f"snapshots={snapshots}",
    ]
    if event_stats:
        details.append(f"events_written={event_stats.get('events', 0)}")
        if "watch_queries" in event_stats:
            details.append(f"watch_queries={event_stats.get('watch_queries', 0)}")
        if event_stats.get("errors"):
            details.append(f"errors={len(event_stats.get('errors', []))}")
    if foundation_stats.get("status") != "skipped":
        details.extend([
            f"foundation={foundation_stats.get('status')}",
            f"articles={foundation_stats.get('articles', 0)}",
            f"report_items={foundation_stats.get('items', 0)}",
            f"artifacts={foundation_stats.get('artifacts', 0)}",
        ])
    return "; ".join(details)


def persist_event_watch_queries(
    domain_id: str,
    event_threads_path: str,
    watch_locales: list[str],
    upsert_fn,
    run_date: str,
) -> int:
    """Generate and persist DB discovery queries from event-thread watch signals."""
    try:
        with open(event_threads_path) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    threads_payload = payload.get("threads") or []
    if not threads_payload:
        return 0

    from stratum.subsystems.event_thread import EventThread, generate_watch_queries

    threads = {}
    for item in threads_payload:
        thread_id = item.get("thread_id") or item.get("id")
        if not thread_id:
            continue
        threads[thread_id] = EventThread(
            id=thread_id,
            title=item.get("title") or item.get("label") or thread_id,
            canonical_question=item.get("canonical_question") or item.get("description") or "",
            status=item.get("status") or "active",
            priority=normalize_thread_priority(item.get("priority", "medium")),
            created=item.get("created") or run_date,
            last_updated=item.get("last_updated") or run_date,
            watch_signals=item.get("watch_signals") or [],
            open_questions=item.get("open_questions") or [],
            close_conditions=item.get("close_conditions") or [],
        )
    if not threads:
        return 0
    return upsert_fn(domain_id, generate_watch_queries(threads, locales=watch_locales), run_date=run_date)


def normalize_thread_priority(priority) -> str:
    """Normalize DB/LLM priority shapes to event-thread priority labels."""
    if isinstance(priority, str):
        value = priority.lower().strip()
        if value in {"high", "medium", "low"}:
            return value
        if value.isdigit():
            priority = int(value)
    if isinstance(priority, (int, float)):
        if priority <= 1:
            return "high"
        if priority == 2:
            return "medium"
    return "low" if priority == 3 else "medium"
