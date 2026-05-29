"""ingest.py — Database ingestion functions for pipeline post-processing.

All functions take a domain and write to {WORKSPACE}/data/{domain}/{domain}.db.
None of them touch files — they pure SQLite operations reading from in-memory data.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

from stratum.db.connection import get_db

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════
# WRITE functions — called by pipeline post-processing
# ═══════════════════════════════════════════════════════════════

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

    try:
        threads_data = data.get('threads', [])

        for t in threads_data:
            thread_id = t.get('thread_id', t.get('id', ''))
            if not thread_id:
                continue

            # Upsert thread
            existing = conn.execute('SELECT id FROM threads WHERE id = ?', (thread_id,)).fetchone()
            if existing:
                conn.execute('''
                    UPDATE threads SET status = ?, last_event_date = ?, event_count_daily = event_count_daily + 1
                    WHERE id = ?
                ''', (t.get('status', 'active'), run_date, thread_id))
            else:
                conn.execute('''
                    INSERT INTO threads (id, label, description, status, priority, first_event_date, last_event_date, event_count_daily)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ''', (
                    thread_id,
                    t.get('label', t.get('title', thread_id)),
                    t.get('description', ''),
                    t.get('status', 'emerging'),
                    t.get('priority', 3),
                    run_date,
                    run_date,
                ))
                stats['new_threads'] += 1

            # Insert event
            event_id = f"ev-{run_date}-{thread_id}"
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
                f"daily-{run_date}",
                now,
                t.get('status', 'active'),
                t.get('priority', 3),
            ))
            stats['events'] += 1

            # Thread-entity association
            for eid in t.get('entity_ids', t.get('entities', [])):
                conn.execute('''
                    INSERT OR IGNORE INTO thread_entities (thread_id, entity_id, role)
                    VALUES (?, ?, 'subject')
                ''', (thread_id, eid))

        # Auto-create missing threads referenced by causal_edges
        referenced_ids = set()
        for ce in data.get('causal_edges', []):
            for key in ('cause_thread_id', 'effect_thread_id'):
                tid = ce.get(key, '')
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

        # Causal edges
        for ce in data.get('causal_edges', []):
            ce_id = ce.get('id', f"ce-{run_date}-{stats['causal_edges']:03d}")
            conn.execute('''
                INSERT OR REPLACE INTO causal_edges (id, cause_thread_id, effect_thread_id, mechanism, confidence, scale,
                                                     source_briefing, created_at)
                VALUES (?, ?, ?, ?, ?, 'daily', ?, ?)
            ''', (
                ce_id,
                ce.get('cause_thread_id', ''),
                ce.get('effect_thread_id', ''),
                ce.get('mechanism', ''),
                ce.get('confidence', 'B'),
                f"daily-{run_date}",
                now,
            ))
            stats['causal_edges'] += 1

        # Judgments
        for jd in data.get('judgments', []):
            jd_id = jd.get('id', f"jd-{run_date}-{stats['judgments']:03d}")
            conn.execute('''
                INSERT OR REPLACE INTO judgments (id, target_type, target_entity_ids, target_thread_ids, hypothesis,
                                                  confidence, expected_verification, scale, source_briefing, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'daily', ?, ?)
            ''', (
                jd_id,
                jd.get('target_type', 'entity'),
                json.dumps(jd.get('target_entity_ids', []), ensure_ascii=False),
                json.dumps(jd.get('target_thread_ids', []), ensure_ascii=False),
                jd.get('hypothesis', ''),
                jd.get('confidence', 'B'),
                jd.get('expected_verification', ''),
                f"daily-{run_date}",
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


def ingest_entity_snapshots(domain: str, scale: str, period: str) -> int:
    """Aggregate current entity data into entity_snapshots for this period.

    Returns number of snapshots written.
    """
    conn = get_db(domain)
    count = 0

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

            # Calculate importance delta (simplified: 0 for now, will be filled by source-profiler)
            prev = conn.execute('''
                SELECT importance_delta FROM entity_snapshots
                WHERE entity_id = ? AND scale = ? AND period < ?
                ORDER BY period DESC LIMIT 1
            ''', (eid, scale, period)).fetchone()
            delta = 0.0  # Placeholder — computed by source-profiler later

            conn.execute('''
                INSERT OR REPLACE INTO entity_snapshots (entity_id, scale, period, status, key_events, article_count,
                                                         thread_ids, importance_delta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                eid, scale, period, e['status'],
                json.dumps(key_events, ensure_ascii=False),
                0,  # article_count placeholder
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


def update_entities_after_run(domain: str, entity_stats: list[dict]) -> int:
    """Update entities after a pipeline run: last_seen, article counts.

    entity_stats: [{'id': 'cxmt', 'article_count_today': 3}, ...]
    Returns number of entities updated.
    """
    conn = get_db(domain)
    count = 0
    today = datetime.now(CST).strftime('%Y-%m-%d')

    try:
        for es in entity_stats:
            conn.execute('''
                UPDATE entities SET last_seen = ?, article_count_7d = article_count_7d + ?
                WHERE id = ?
            ''', (today, es.get('article_count_today', 0), es['id']))
            count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


def update_query_stats(domain: str, query_stats: list[dict]) -> int:
    """Update query stats after a pipeline run.

    query_stats: [{'id': 'q-detection-001', 'articles_found': 3}, ...]
    Returns number of queries updated.
    """
    conn = get_db(domain)
    count = 0
    today = datetime.now(CST).strftime('%Y-%m-%d')

    try:
        for qs in query_stats:
            conn.execute('''
                UPDATE queries SET last_run = ?, hit_count_7d = hit_count_7d + ?
                WHERE id = ?
            ''', (today, qs.get('articles_found', 0), qs['id']))
            count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

    return count


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
# READ functions — used by Search stage and cascade consumers
# ═══════════════════════════════════════════════════════════════

def get_queries_for_scale(domain: str, scale: str) -> list[dict]:
    """Get queries appropriate for a given scale.

    Returns list of {text, locale, intent, id} dicts.
    """
    # scale → intent mapping
    scale_intents = {
        'daily': ['detection'],
        'weekly': ['detection', 'confirmation', 'verification'],
        'monthly': ['confirmation', 'verification'],
        'quarterly': ['context', 'structural', 'verification'],
        'yearly': ['structural'],
    }
    intents = scale_intents.get(scale, ['detection'])

    # scale → thread status filter
    scale_thread_status = {
        'daily': ['emerging', 'active'],
        'weekly': ['emerging', 'active', 'cooling'],
        'monthly': ['active', 'cooling', 'dormant'],
        'quarterly': ['active', 'cooling', 'dormant', 'resolved'],
        'yearly': ['cooling', 'dormant', 'resolved'],
    }
    thread_statuses = scale_thread_status.get(scale, ['emerging', 'active'])

    conn = get_db(domain)
    try:
        placeholders = ','.join(['?'] * len(intents))
        status_placeholders = ','.join(['?'] * len(thread_statuses))

        rows = conn.execute(f'''
            SELECT q.id, q.text, q.locale, q.intent
            FROM queries q
            LEFT JOIN threads t ON q.thread_id = t.id
            WHERE q.status = 'active'
              AND (q.thread_id IS NULL
                   OR (t.status IN ({status_placeholders})))
              AND q.intent IN ({placeholders})
            ORDER BY q.intent, q.locale
        ''', thread_statuses + intents).fetchall()

        return [{'id': r['id'], 'text': r['text'], 'locale': r['locale'], 'intent': r['intent']} for r in rows]
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
        return [dict(r) for r in rows]
    finally:
        conn.close()


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
