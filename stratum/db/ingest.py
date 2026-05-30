"""ingest.py — Database ingestion functions for pipeline post-processing.

All functions take a domain and write through stratum.db.connection.get_db().
They do not read pipeline artifacts directly; callers pass in-memory data or
explicit artifact paths for the few import-style helpers.
"""

from __future__ import annotations

import json
import os
import hashlib
import re
from datetime import datetime, timezone, timedelta

from stratum.db.connection import get_db
from stratum.subsystems.search.models import normalize_include_domains

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════
# WRITE functions — called by pipeline post-processing
# ═══════════════════════════════════════════════════════════════

def _sync_thread_entities(conn, thread_id: str) -> None:
    """Rebuild subject entity links for a thread from its stored events."""
    entity_ids = set()
    rows = conn.execute(
        'SELECT entity_ids FROM events WHERE thread_id = ?',
        (thread_id,),
    ).fetchall()
    for row in rows:
        raw = row['entity_ids'] if row['entity_ids'] else '[]'
        try:
            values = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            values = []
        for entity_id in values:
            if entity_id:
                entity_ids.add(entity_id)

    has_entities_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'entities'"
    ).fetchone()
    if entity_ids and has_entities_table:
        known_entities = {
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM entities WHERE id IN ({','.join(['?'] * len(entity_ids))})",
                tuple(sorted(entity_ids)),
            ).fetchall()
        }
    else:
        known_entities = entity_ids

    conn.execute(
        "DELETE FROM thread_entities WHERE thread_id = ? AND role = 'subject'",
        (thread_id,),
    )
    for entity_id in sorted(known_entities):
        conn.execute('''
            INSERT OR IGNORE INTO thread_entities (thread_id, entity_id, role)
            VALUES (?, ?, 'subject')
        ''', (thread_id, entity_id))


def _priority_rank(priority) -> int:
    """Normalize LLM/event-thread priority labels to DB sort ranks."""
    if isinstance(priority, str):
        value = priority.strip().lower()
        if value in {"high", "p1", "urgent"}:
            return 1
        if value in {"medium", "med", "p2"}:
            return 2
        if value in {"low", "p3"}:
            return 3
        try:
            priority = int(value)
        except ValueError:
            return 3
    if isinstance(priority, (int, float)):
        if priority <= 1:
            return 1
        if priority == 2:
            return 2
        return 3
    return 3


def ingest_daily_events(event_threads_path: str, domain: str, run_date: str) -> dict:
    """Read event-threads.json and write events/threads/thread_entities/causal_edges/judgments.

    Returns stats: {ingested, rejected, errors}
    """
    if not os.path.exists(event_threads_path):
        return {'events': 0, 'causal_edges': 0, 'judgments': 0, 'new_threads': 0, 'errors': []}

    with open(event_threads_path) as f:
        data = json.load(f)

    conn = get_db(domain)
    stats = {'events': 0, 'causal_edges': 0, 'judgments': 0, 'new_threads': 0, 'errors': []}
    now = datetime.now(CST).isoformat()
    source_briefing = f"daily-{run_date}"

    try:
        threads_data = data.get('threads', [])

        for t in threads_data:
            thread_id = t.get('thread_id', t.get('id', ''))
            if not thread_id:
                continue

            event_id = f"ev-{run_date}-{thread_id}"
            existing_event = conn.execute('SELECT id FROM events WHERE id = ?', (event_id,)).fetchone()
            event_count_delta = 0 if existing_event else 1
            priority_rank = _priority_rank(t.get('priority', 3))

            # Upsert thread
            existing = conn.execute('SELECT id FROM threads WHERE id = ?', (thread_id,)).fetchone()
            if existing:
                conn.execute('''
                    UPDATE threads
                       SET status = ?,
                           priority = ?,
                           last_event_date = ?,
                           event_count_daily = event_count_daily + ?
                    WHERE id = ?
                ''', (t.get('status', 'active'), priority_rank, run_date, event_count_delta, thread_id))
            else:
                conn.execute('''
                    INSERT INTO threads (id, label, description, status, priority, first_event_date, last_event_date, event_count_daily)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    thread_id,
                    t.get('label', t.get('title', thread_id)),
                    t.get('description', ''),
                    t.get('status', 'emerging'),
                    priority_rank,
                    run_date,
                    run_date,
                    event_count_delta,
                ))
                stats['new_threads'] += 1

            # Insert event
            conn.execute('''
                INSERT OR REPLACE INTO events (id, thread_id, scale, date, title, article_ids, entity_ids, term_ids,
                                               source_domains, confidence, briefing_id, created_at, status, priority)
                VALUES (?, ?, 'daily', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_id, thread_id, run_date,
                t.get('title', t.get('label', '')),
                json.dumps(t.get('article_ids', []), ensure_ascii=False),
                json.dumps(t.get('entity_ids', t.get('entities', [])), ensure_ascii=False),
                json.dumps(t.get('term_ids', t.get('terms', [])), ensure_ascii=False),
                json.dumps(t.get('source_domains', []), ensure_ascii=False),
                t.get('confidence', 'B'),
                source_briefing,
                now,
                t.get('status', 'active'),
                priority_rank,
            ))
            stats['events'] += 1

            _sync_thread_entities(conn, thread_id)

        # Auto-create missing threads referenced by causal_edges
        referenced_ids = set()
        for ce in data.get('causal_edges', []):
            for key in ('cause_thread_id', 'effect_thread_id'):
                tid = ce.get(key, '')
                if tid:
                    referenced_ids.add(tid)
        for jd in data.get('judgments', []):
            for tid in jd.get('target_thread_ids', []) or []:
                if tid:
                    referenced_ids.add(tid)
        if referenced_ids:
            placeholders = ','.join(['?'] * len(referenced_ids))
            existing = {r['id'] for r in conn.execute(
                f'SELECT id FROM threads WHERE id IN ({placeholders})',
                tuple(referenced_ids)
            ).fetchall()}
            for tid in referenced_ids - existing:
                conn.execute('''
                    INSERT INTO threads (id, label, description, status, priority, first_event_date, last_event_date, event_count_daily)
                    VALUES (?, ?, '', 'emerging', 3, ?, ?, 0)
                ''', (tid, tid, run_date, run_date))
                stats['new_threads'] += 1

        conn.execute(
            "DELETE FROM causal_edges WHERE source_briefing = ? AND verified IS NULL",
            (source_briefing,),
        )
        conn.execute('''
            DELETE FROM judgments
             WHERE source_briefing = ?
               AND (result IS NULL OR result = 'pending')
        ''', (source_briefing,))

        # Causal edges
        for ce in data.get('causal_edges', []):
            ce_id = ce.get('id', f"ce-{run_date}-{stats['causal_edges']:03d}")
            existing_ce = conn.execute(
                "SELECT verified, verified_at, verified_by_scale FROM causal_edges WHERE id = ?",
                (ce_id,),
            ).fetchone()
            conn.execute('''
                INSERT OR REPLACE INTO causal_edges (id, cause_thread_id, effect_thread_id, mechanism, confidence, scale,
                                                     source_briefing, verified, verified_at, verified_by_scale, created_at)
                VALUES (?, ?, ?, ?, ?, 'daily', ?, ?, ?, ?, ?)
            ''', (
                ce_id,
                ce.get('cause_thread_id', ''),
                ce.get('effect_thread_id', ''),
                ce.get('mechanism', ''),
                ce.get('confidence', 'B'),
                source_briefing,
                existing_ce['verified'] if existing_ce else None,
                existing_ce['verified_at'] if existing_ce else None,
                existing_ce['verified_by_scale'] if existing_ce else None,
                now,
            ))
            stats['causal_edges'] += 1

        # Judgments
        for jd in data.get('judgments', []):
            jd_id = jd.get('id', f"jd-{run_date}-{stats['judgments']:03d}")
            existing_jd = conn.execute(
                "SELECT result, verified_at, verified_by_scale, actual_outcome FROM judgments WHERE id = ?",
                (jd_id,),
            ).fetchone()
            conn.execute('''
                INSERT OR REPLACE INTO judgments (id, target_type, target_entity_ids, target_thread_ids, hypothesis,
                                                  confidence, expected_verification, scale, source_briefing, result,
                                                  verified_at, verified_by_scale, actual_outcome, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'daily', ?, ?, ?, ?, ?, ?)
            ''', (
                jd_id,
                jd.get('target_type', 'entity'),
                json.dumps(jd.get('target_entity_ids', []), ensure_ascii=False),
                json.dumps(jd.get('target_thread_ids', []), ensure_ascii=False),
                jd.get('hypothesis', ''),
                jd.get('confidence', 'B'),
                jd.get('expected_verification', ''),
                source_briefing,
                existing_jd['result'] if existing_jd else None,
                existing_jd['verified_at'] if existing_jd else None,
                existing_jd['verified_by_scale'] if existing_jd else None,
                existing_jd['actual_outcome'] if existing_jd else None,
                now,
            ))
            stats['judgments'] += 1

        conn.commit()
    except Exception as e:
        stats['errors'].append(str(e))
        conn.rollback()
    finally:
        conn.close()

    return stats


def ingest_entity_snapshots(
    domain: str,
    scale: str,
    period: str,
    entity_article_counts: dict[str, int] | None = None,
) -> int:
    """Aggregate current entity data into entity_snapshots for this period.

    entity_article_counts maps entity id to article count for this run/period.
    Returns number of snapshots written.
    """
    conn = get_db(domain)
    count = 0
    entity_article_counts = entity_article_counts or {}

    try:
        entities = conn.execute('SELECT id, status FROM entities').fetchall()
        for e in entities:
            eid = e['id']
            # Get active threads for this entity
            threads = conn.execute('''
                SELECT thread_id FROM thread_entities WHERE entity_id = ?
            ''', (eid,)).fetchall()
            thread_ids = [t['thread_id'] for t in threads]

            # Get recent events for key_events
            events = conn.execute('''
                SELECT title FROM events WHERE thread_id IN (
                    SELECT thread_id FROM thread_entities WHERE entity_id = ?
                ) AND scale = ? ORDER BY date DESC LIMIT 5
            ''', (eid, scale)).fetchall()
            key_events = [ev['title'] for ev in events]

            # Future scoring jobs can replace this neutral placeholder.
            delta = 0.0

            conn.execute('''
                INSERT OR REPLACE INTO entity_snapshots (entity_id, scale, period, status, key_events, article_count,
                                                         thread_ids, importance_delta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                eid, scale, period, e['status'],
                json.dumps(key_events, ensure_ascii=False),
                int(entity_article_counts.get(eid, 0) or 0),
                json.dumps(thread_ids, ensure_ascii=False),
                round(delta, 4),
            ))
            count += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


def update_entities_after_run(
    domain: str,
    entity_stats: list[dict],
    run_date: str | None = None,
    scale: str = "daily",
) -> int:
    """Update entities after a pipeline run: last_seen, article counts.

    entity_stats: [{'id': 'cxmt', 'article_count_today': 3}, ...]
    Returns number of entities updated.
    """
    conn = get_db(domain)
    count = 0
    today = run_date or datetime.now(CST).strftime('%Y-%m-%d')

    try:
        entity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(entities)").fetchall()}
        has_snapshots = bool(conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'entity_snapshots'"
        ).fetchone())
        for es in entity_stats:
            article_count = int(es.get('article_count_today', 0) or 0)
            entity_id = es['id']
            cur = conn.execute('''
                UPDATE entities
                   SET last_seen = ?
                WHERE id = ?
            ''', (today, entity_id))
            if cur.rowcount:
                if run_date and has_snapshots:
                    _upsert_entity_article_snapshot(conn, entity_id, scale, run_date, article_count)
                    _refresh_entity_rollups(conn, entity_id, today, scale, entity_columns)
                else:
                    conn.execute('''
                        UPDATE entities
                           SET article_count_7d = MAX(0, article_count_7d + ?)
                         WHERE id = ?
                    ''', (article_count, entity_id))
                count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


def _upsert_entity_article_snapshot(
    conn,
    entity_id: str,
    scale: str,
    period: str,
    article_count: int,
) -> None:
    """Write the per-period article count without clobbering richer snapshot fields."""
    existing = conn.execute('''
        SELECT entity_id FROM entity_snapshots
        WHERE entity_id = ? AND scale = ? AND period = ?
    ''', (entity_id, scale, period)).fetchone()
    if existing:
        conn.execute('''
            UPDATE entity_snapshots
               SET article_count = ?
             WHERE entity_id = ? AND scale = ? AND period = ?
        ''', (article_count, entity_id, scale, period))
    else:
        conn.execute('''
            INSERT INTO entity_snapshots (entity_id, scale, period, article_count)
            VALUES (?, ?, ?, ?)
        ''', (entity_id, scale, period, article_count))


def _refresh_entity_rollups(
    conn,
    entity_id: str,
    run_date: str,
    scale: str,
    entity_columns: set[str],
) -> None:
    """Recompute entity rolling article counters from periodic snapshots."""
    updates = []
    values = []
    if "article_count_7d" in entity_columns:
        row = conn.execute('''
            SELECT COALESCE(SUM(article_count), 0) AS total
              FROM entity_snapshots
             WHERE entity_id = ?
               AND scale = ?
               AND period >= date(?, '-6 days')
               AND period <= ?
        ''', (entity_id, scale, run_date, run_date)).fetchone()
        updates.append("article_count_7d = ?")
        values.append(int(row["total"] or 0))

    if "article_count_30d" in entity_columns:
        row = conn.execute('''
            SELECT COALESCE(SUM(article_count), 0) AS total
              FROM entity_snapshots
             WHERE entity_id = ?
               AND scale = ?
               AND period >= date(?, '-29 days')
               AND period <= ?
        ''', (entity_id, scale, run_date, run_date)).fetchone()
        updates.append("article_count_30d = ?")
        values.append(int(row["total"] or 0))

    if not updates:
        return

    conn.execute(
        f"UPDATE entities SET {', '.join(updates)} WHERE id = ?",
        values + [entity_id],
    )


def update_query_stats(domain: str, query_stats: list[dict], run_date: str | None = None) -> int:
    """Update query stats after a pipeline run.

    query_stats accepts legacy or Search subsystem shape:
    [{'id': 'q-detection-001', 'articles_found': 3}, ...]
    [{'query_id': 'q-detection-001', 'results_count': 3}, ...]
    Returns number of queries updated.
    """
    conn = get_db(domain)
    count = 0
    today = run_date or datetime.now(CST).strftime('%Y-%m-%d')
    now = datetime.now(CST).isoformat()

    try:
        query_columns = {row["name"] for row in conn.execute("PRAGMA table_info(queries)").fetchall()}
        conn.execute('''
            CREATE TABLE IF NOT EXISTS query_run_stats (
                query_id TEXT NOT NULL,
                run_date TEXT NOT NULL,
                results_count INTEGER DEFAULT 0,
                status TEXT,
                updated_at TEXT,
                PRIMARY KEY (query_id, run_date)
            )
        ''')
        for qs in query_stats:
            query_id = qs.get('id') or qs.get('query_id')
            if not query_id:
                continue
            articles_found = int(qs.get('articles_found', qs.get('results_count', 0)) or 0)
            cur = conn.execute("UPDATE queries SET last_run = ? WHERE id = ?", (today, query_id))
            if cur.rowcount:
                conn.execute('''
                    INSERT OR REPLACE INTO query_run_stats
                        (query_id, run_date, results_count, status, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (query_id, today, articles_found, qs.get('status'), now))
                _refresh_query_rollups(conn, query_id, today, query_columns)
                count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


def upsert_watch_queries(domain: str, watch_queries: list[dict], run_date: str | None = None) -> int:
    """Persist event-thread watch queries into the active Search query table."""
    conn = get_db(domain)
    count = 0
    now = datetime.now(CST).isoformat()
    created_at = run_date or datetime.now(CST).strftime('%Y-%m-%d')

    try:
        query_columns = {row["name"] for row in conn.execute("PRAGMA table_info(queries)").fetchall()}
        has_dimension = "dimension" in query_columns
        has_include_domains = "include_domains" in query_columns

        for item in watch_queries or []:
            text = str(item.get("query") or item.get("text") or "").strip()
            locale = str(item.get("locale") or "en").strip() or "en"
            thread_id = _watch_query_thread_id(item)
            if not text or not thread_id:
                continue

            query_id = item.get("id") or item.get("query_id") or _watch_query_id(thread_id, locale, text)
            values = {
                "id": query_id,
                "text": text,
                "locale": locale,
                "intent": item.get("intent", "verification"),
                "dimension": item.get("dimension", "thread_watch"),
                "include_domains": _normalize_include_domains(
                    item.get("include_domains", item.get("domains"))
                ),
                "thread_id": thread_id,
                "created_at": created_at,
            }
            if has_dimension and has_include_domains:
                cur = conn.execute('''
                    UPDATE queries
                       SET text = ?,
                           locale = ?,
                           intent = ?,
                           dimension = ?,
                           include_domains = ?,
                           thread_id = ?,
                           status = 'active'
                     WHERE id = ?
                ''', (
                    values["text"], values["locale"], values["intent"],
                    values["dimension"],
                    json.dumps(values["include_domains"], ensure_ascii=False),
                    values["thread_id"], values["id"],
                ))
                if cur.rowcount == 0:
                    conn.execute('''
                        INSERT INTO queries
                            (id, text, locale, intent, dimension, include_domains, thread_id, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    ''', (
                        values["id"], values["text"], values["locale"], values["intent"],
                        values["dimension"],
                        json.dumps(values["include_domains"], ensure_ascii=False),
                        values["thread_id"], values["created_at"],
                    ))
            elif has_dimension:
                cur = conn.execute('''
                    UPDATE queries
                       SET text = ?,
                           locale = ?,
                           intent = ?,
                           dimension = ?,
                           thread_id = ?,
                           status = 'active'
                     WHERE id = ?
                ''', (
                    values["text"], values["locale"], values["intent"],
                    values["dimension"], values["thread_id"], values["id"],
                ))
                if cur.rowcount == 0:
                    conn.execute('''
                        INSERT INTO queries
                            (id, text, locale, intent, dimension, thread_id, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                    ''', (
                        values["id"], values["text"], values["locale"], values["intent"],
                        values["dimension"], values["thread_id"], values["created_at"],
                    ))
            else:
                cur = conn.execute('''
                    UPDATE queries
                       SET text = ?,
                           locale = ?,
                           intent = ?,
                           thread_id = ?,
                           status = 'active'
                     WHERE id = ?
                ''', (
                    values["text"], values["locale"], values["intent"],
                    values["thread_id"], values["id"],
                ))
                if cur.rowcount == 0:
                    conn.execute('''
                        INSERT INTO queries
                            (id, text, locale, intent, thread_id, status, created_at)
                        VALUES (?, ?, ?, ?, ?, 'active', ?)
                    ''', (
                        values["id"], values["text"], values["locale"], values["intent"],
                        values["thread_id"], values["created_at"],
                    ))
            count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


def _normalize_include_domains(domains) -> list[str]:
    return normalize_include_domains(domains)


def _parse_include_domains(value) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        parsed = value
    return _normalize_include_domains(parsed)


def _watch_query_thread_id(item: dict) -> str:
    thread_id = str(item.get("thread_id") or "").strip()
    if thread_id:
        return thread_id
    source = str(item.get("source") or "")
    if source.startswith("thread:"):
        return source.split(":", 1)[1].strip()
    return ""


def _watch_query_id(thread_id: str, locale: str, text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", thread_id).strip("-").lower() or "thread"
    digest = hashlib.sha1(f"{thread_id}|{locale}|{text}".encode("utf-8")).hexdigest()[:10]
    return f"q-watch-{slug}-{locale.lower()}-{digest}"


def _refresh_query_rollups(conn, query_id: str, run_date: str, query_columns: set[str]) -> None:
    """Recompute query quality counters from the per-day ledger."""
    updates = []
    values = []
    if "hit_count_7d" in query_columns:
        row = conn.execute('''
            SELECT COALESCE(SUM(results_count), 0) AS total
              FROM query_run_stats
             WHERE query_id = ?
               AND run_date >= date(?, '-6 days')
               AND run_date <= ?
        ''', (query_id, run_date, run_date)).fetchone()
        updates.append("hit_count_7d = ?")
        values.append(int(row["total"] or 0))

    if "hit_count_30d" in query_columns:
        row = conn.execute('''
            SELECT COALESCE(SUM(results_count), 0) AS total
              FROM query_run_stats
             WHERE query_id = ?
               AND run_date >= date(?, '-29 days')
               AND run_date <= ?
        ''', (query_id, run_date, run_date)).fetchone()
        updates.append("hit_count_30d = ?")
        values.append(int(row["total"] or 0))

    if "avg_articles" in query_columns:
        row = conn.execute('''
            SELECT COALESCE(AVG(results_count), 0) AS avg_results
              FROM query_run_stats
             WHERE query_id = ?
               AND run_date >= date(?, '-29 days')
               AND run_date <= ?
        ''', (query_id, run_date, run_date)).fetchone()
        updates.append("avg_articles = ?")
        values.append(float(row["avg_results"] or 0))

    if not updates:
        return

    conn.execute(
        f"UPDATE queries SET {', '.join(updates)} WHERE id = ?",
        values + [query_id],
    )


def ingest_keyword_article(domain: str, article_keywords: list[dict]) -> int:
    """Write keyword-article associations.

    article_keywords: [{'article_id': 'art-001', 'keyword_id': 'kw-hbm4', 'source': 'title'}, ...]
    Returns number of associations written.
    """
    conn = get_db(domain)
    count = 0

    try:
        for ak in article_keywords:
            conn.execute('''
                INSERT OR IGNORE INTO keyword_article (article_id, keyword_id, source)
                VALUES (?, ?, ?)
            ''', (ak['article_id'], ak['keyword_id'], ak.get('source', 'title')))
            count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


def ingest_keyword_event(domain: str, event_keywords: list[dict]) -> int:
    """Write keyword-event associations.

    event_keywords: [{'event_id': 'ev-2026-05-30-et-001', 'keyword_id': 'kw-hbm4', 'weight': 2}, ...]
    Returns number of associations written.
    """
    conn = get_db(domain)
    count = 0

    try:
        for ek in event_keywords:
            conn.execute('''
                INSERT OR IGNORE INTO keyword_event (event_id, keyword_id, weight)
                VALUES (?, ?, ?)
            ''', (ek['event_id'], ek['keyword_id'], ek.get('weight', 1)))
            count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


def ingest_cascade_log(domain: str, log_data: dict) -> None:
    """Write a cascade run log entry.

    log_data: {scale, period, run_at, consumed_from, consumed_window,
               consumed_causal_edges, consumed_judgments, fresh_search_articles,
               produced_judgments, status}
    """
    conn = get_db(domain)

    try:
        log_id = f"log-{log_data['scale']}-{log_data['period']}"
        conn.execute('''
            INSERT OR REPLACE INTO cascade_logs (id, scale, period, run_at, consumed_from, consumed_window,
                                                  consumed_causal_edges, consumed_judgments,
                                                  fresh_search_articles, produced_judgments, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            log_id,
            log_data['scale'],
            log_data['period'],
            log_data.get('run_at', datetime.now(CST).isoformat()),
            log_data.get('consumed_from', ''),
            log_data.get('consumed_window', ''),
            log_data.get('consumed_causal_edges', 0),
            log_data.get('consumed_judgments', 0),
            log_data.get('fresh_search_articles', 0),
            log_data.get('produced_judgments', 0),
            log_data.get('status', 'ok'),
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def ingest_coverage(domain: str, coverage_data: dict) -> None:
    """Write a coverage report.

    coverage_data: {scale, period, covered_threads, missed_threads, stale_entities,
                    missed_dimensions, source_contribution}
    """
    conn = get_db(domain)

    try:
        cov_id = f"cov-{coverage_data['scale']}-{coverage_data['period']}"
        conn.execute('''
            INSERT OR REPLACE INTO coverage (id, scale, period, covered_threads, missed_threads,
                                              stale_entities, missed_dimensions, source_contribution)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            cov_id,
            coverage_data['scale'],
            coverage_data['period'],
            json.dumps(coverage_data.get('covered_threads', []), ensure_ascii=False),
            json.dumps(coverage_data.get('missed_threads', []), ensure_ascii=False),
            json.dumps(coverage_data.get('stale_entities', []), ensure_ascii=False),
            json.dumps(coverage_data.get('missed_dimensions', []), ensure_ascii=False),
            json.dumps(coverage_data.get('source_contribution', {}), ensure_ascii=False),
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# READ functions — used by Search, monitoring, and higher-scale consumers
# ═══════════════════════════════════════════════════════════════

def get_queries_for_scale(domain: str, scale: str) -> list[dict]:
    """Get queries appropriate for a given scale.

    Returns list of {text, locale, intent, id} dicts.
    """
    # scale → intent mapping
    scale_intents = {
        'daily': ['detection', 'verification'],
        'weekly': ['detection', 'confirmation', 'verification'],
        'monthly': ['confirmation', 'verification'],
        'quarterly': ['context', 'structural', 'verification'],
        'yearly': ['structural'],
    }
    intents = scale_intents.get(scale, ['detection'])

    # scale → thread status filter
    scale_thread_status = {
        'daily': ['emerging', 'active', 'cooling'],
        'weekly': ['emerging', 'active', 'cooling'],
        'monthly': ['active', 'cooling', 'dormant'],
        'quarterly': ['active', 'cooling', 'dormant', 'resolved'],
        'yearly': ['cooling', 'dormant', 'resolved'],
    }
    thread_statuses = scale_thread_status.get(scale, ['emerging', 'active'])

    conn = get_db(domain)
    try:
        query_columns = {row["name"] for row in conn.execute("PRAGMA table_info(queries)").fetchall()}
        dimension_expr = "q.dimension" if "dimension" in query_columns else "'general'"
        include_domains_expr = "q.include_domains" if "include_domains" in query_columns else "NULL"
        placeholders = ','.join(['?'] * len(intents))
        status_placeholders = ','.join(['?'] * len(thread_statuses))

        rows = conn.execute(f'''
            SELECT q.id, q.text, q.locale, q.intent,
                   {dimension_expr} AS dimension,
                   {include_domains_expr} AS include_domains
            FROM queries q
            LEFT JOIN threads t ON q.thread_id = t.id
            WHERE q.status = 'active'
              AND (q.thread_id IS NULL
                   OR (t.status IN ({status_placeholders})))
              AND q.intent IN ({placeholders})
            ORDER BY q.intent, q.locale
        ''', thread_statuses + intents).fetchall()

        queries = []
        for r in rows:
            item = {
                'id': r['id'],
                'text': r['text'],
                'locale': r['locale'],
                'intent': r['intent'],
                'dimension': r['dimension'] or 'general',
            }
            include_domains = _parse_include_domains(r['include_domains'])
            if include_domains:
                item['include_domains'] = include_domains
            queries.append(item)
        return queries
    finally:
        conn.close()


def get_upstream_structured_data(domain: str, from_scale: str, start_date: str, end_date: str) -> dict:
    """Get upstream structured data for cascade consumption.

    Returns {causal_edges, judgments, entities, threads}
    """
    conn = get_db(domain)
    try:
        causal_edges = [dict(r) for r in conn.execute('''
            SELECT * FROM causal_edges
            WHERE scale = ? AND created_at >= ? AND created_at <= ?
            ORDER BY created_at
        ''', (from_scale, start_date, end_date)).fetchall()]

        judgments = [dict(r) for r in conn.execute('''
            SELECT * FROM judgments
            WHERE scale = ? AND created_at >= ? AND created_at <= ?
            ORDER BY created_at
        ''', (from_scale, start_date, end_date)).fetchall()]

        entities = [dict(r) for r in conn.execute('''
            SELECT * FROM entities WHERE last_seen >= ?
        ''', (start_date,)).fetchall()]

        threads = [dict(r) for r in conn.execute('''
            SELECT * FROM threads WHERE last_event_date >= ?
            ORDER BY priority ASC, event_count_daily DESC
        ''', (start_date,)).fetchall()]

        return {
            'causal_edges': causal_edges,
            'judgments': judgments,
            'entities': entities,
            'threads': threads,
        }
    finally:
        conn.close()


def get_last_cascade_run(domain: str, scale: str) -> dict | None:
    """Get the last cascade run log for a scale. Returns None if no prior run."""
    conn = get_db(domain)
    try:
        row = conn.execute('''
            SELECT * FROM cascade_logs WHERE scale = ? ORDER BY run_at DESC LIMIT 1
        ''', (scale,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_entity_timeline(domain: str, entity_id: str) -> list[dict]:
    """Get all snapshots for an entity across all scales, ordered by period."""
    conn = get_db(domain)
    try:
        rows = conn.execute('''
            SELECT * FROM entity_snapshots WHERE entity_id = ? ORDER BY period
        ''', (entity_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_thread_timeline(domain: str, thread_id: str) -> list[dict]:
    """Get all events for a thread across all scales, ordered by date."""
    conn = get_db(domain)
    try:
        rows = conn.execute('''
            SELECT * FROM events WHERE thread_id = ? ORDER BY date
        ''', (thread_id,)).fetchall()
        return [_event_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _json_list(value) -> list:
    """Return a JSON-array column as a Python list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _event_row_to_dict(row) -> dict:
    event = dict(row)
    for field in ("article_ids", "entity_ids", "term_ids", "source_domains"):
        event[field] = _json_list(event.get(field))
    return event


def _events_for_json_member(
    domain: str,
    column: str,
    member_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    scale: str | None = None,
    limit: int = 100,
    order: str = "desc",
) -> list[dict]:
    """Fetch events whose JSON-array column contains member_id.

    SQLite JSON1 is not guaranteed to be available in every local Python build,
    so filtering the denormalized JSON columns in Python keeps these read APIs
    portable. Date and scale predicates stay in SQL to keep scans bounded.
    """
    order_sql = "ASC" if order.lower() == "asc" else "DESC"
    clauses = []
    params = []
    if start_date:
        clauses.append("date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("date <= ?")
        params.append(end_date)
    if scale:
        clauses.append("scale = ?")
        params.append(scale)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_db(domain)
    try:
        rows = conn.execute(f'''
            SELECT * FROM events
            {where}
            ORDER BY date {order_sql}, priority ASC
        ''', params).fetchall()
        events = []
        for row in rows:
            event = _event_row_to_dict(row)
            if member_id in event.get(column, []):
                events.append(event)
                if len(events) >= limit:
                    break
        return events
    finally:
        conn.close()


def get_entity_events(
    domain: str,
    entity_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    scale: str | None = "daily",
    limit: int = 100,
    order: str = "desc",
) -> list[dict]:
    """Get accumulated events mentioning an entity.

    This is the event-level companion to get_entity_timeline(), which returns
    periodic snapshots. Use it for questions like "Samsung's important events
    over the last six months".
    """
    return _events_for_json_member(
        domain,
        "entity_ids",
        entity_id,
        start_date=start_date,
        end_date=end_date,
        scale=scale,
        limit=limit,
        order=order,
    )


def get_term_events(
    domain: str,
    term_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    scale: str | None = "daily",
    limit: int = 100,
    order: str = "desc",
) -> list[dict]:
    """Get accumulated events mentioning a domain term.

    Use it for key topics such as HBM, NAND, SSD, advanced packaging, or future
    robot-domain terms.
    """
    return _events_for_json_member(
        domain,
        "term_ids",
        term_id,
        start_date=start_date,
        end_date=end_date,
        scale=scale,
        limit=limit,
        order=order,
    )


def get_term_company_progress(
    domain: str,
    term_id: str,
    entity_ids: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    scale: str | None = "daily",
    limit_per_entity: int = 50,
    order: str = "desc",
) -> dict[str, list[dict]]:
    """Group term-related events by mentioned entity.

    This supports comparisons like "HBM progress across Samsung, SK hynix,
    Micron, and CXMT" while staying domain-agnostic for future domains.
    """
    allowed_entities = set(entity_ids) if entity_ids else None
    grouped: dict[str, list[dict]] = {}
    events = get_term_events(
        domain,
        term_id,
        start_date=start_date,
        end_date=end_date,
        scale=scale,
        limit=1000,
        order=order,
    )

    for event in events:
        for entity_id in event.get("entity_ids", []):
            if allowed_entities is not None and entity_id not in allowed_entities:
                continue
            bucket = grouped.setdefault(entity_id, [])
            if len(bucket) < limit_per_entity:
                bucket.append(event)

    return grouped


def get_keyword_cooccurrence(domain: str, keyword_id: str, min_count: int = 3) -> list[dict]:
    """Find keywords that co-occur with the given keyword, ordered by frequency."""
    conn = get_db(domain)
    try:
        rows = conn.execute('''
            SELECT k2.text AS keyword, COUNT(*) AS co_count
            FROM keyword_article ka1
            JOIN keyword_article ka2 ON ka1.article_id = ka2.article_id
            JOIN keywords k1 ON ka1.keyword_id = k1.id
            JOIN keywords k2 ON ka2.keyword_id = k2.id
            WHERE k1.id = ? AND k2.id != ?
            GROUP BY k2.text
            HAVING COUNT(*) >= ?
            ORDER BY co_count DESC
        ''', (keyword_id, keyword_id, min_count)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
