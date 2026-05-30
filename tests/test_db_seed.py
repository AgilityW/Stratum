"""Tests for SQLite seed helpers."""

import json
import sqlite3


def _schema_for_sources(conn):
    conn.execute("""
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            domain TEXT NOT NULL,
            type TEXT NOT NULL,
            url TEXT,
            locale TEXT,
            reliability REAL DEFAULT 0.5,
            status TEXT DEFAULT 'trial',
            added_by TEXT DEFAULT 'seed',
            first_seen TEXT,
            last_seen TEXT,
            tags TEXT
        )
    """)


def test_seed_sources_includes_source_registry_entries():
    from stratum.db.seed import _seed_sources

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _schema_for_sources(conn)

    _seed_sources(conn, {
        "channels": [
            {
                "id": "legacy-feed",
                "name": "Legacy Feed",
                "url": "https://legacy.example.com/feed",
                "type": "MEDIA",
                "locale": "en",
            }
        ],
        "source_registry": {
            "sources": [
                {
                    "id": "micron-newsroom",
                    "name": "Micron News Releases",
                    "urls": ["https://www.micron.com/about/press/news"],
                    "category": "newsroom",
                    "locale": "en",
                    "status": "active",
                }
            ]
        },
    })

    rows = {
        row["id"]: dict(row)
        for row in conn.execute("SELECT id, domain, type, url, status, added_by FROM sources")
    }

    assert set(rows) == {"legacy-feed", "micron-newsroom"}
    assert rows["legacy-feed"]["domain"] == "legacy.example.com"
    assert rows["legacy-feed"]["added_by"] == "seed"
    assert rows["micron-newsroom"]["domain"] == "micron.com"
    assert rows["micron-newsroom"]["type"] == "NEWSROOM"
    assert rows["micron-newsroom"]["added_by"] == "source_registry"


def test_upsert_watch_queries_persists_thread_bound_search_queries(tmp_path, monkeypatch):
    from stratum.db.connection import get_db
    from stratum.db.ingest import upsert_watch_queries

    monkeypatch.setenv("STRATUM_DB_DIR", str(tmp_path))
    conn = get_db("storage")
    conn.execute("""
        INSERT INTO threads (id, label, status)
        VALUES ('et-storage-0001', 'Samsung HBM4', 'cooling')
    """)
    conn.commit()
    conn.close()

    count = upsert_watch_queries("storage", [
        {
            "query": "Samsung HBM4 qualification",
            "locale": "en",
            "source": "thread:et-storage-0001",
        },
        {
            "query": "Samsung HBM4 qualification",
            "locale": "zh-CN",
            "thread_id": "et-storage-0001",
        },
    ], run_date="2026-05-30")

    assert count == 2
    conn = get_db("storage")
    rows = conn.execute("""
        SELECT text, locale, intent, dimension, thread_id, status, created_at
          FROM queries
         ORDER BY locale
    """).fetchall()
    conn.close()

    assert [r["locale"] for r in rows] == ["en", "zh-CN"]
    assert all(r["text"] == "Samsung HBM4 qualification" for r in rows)
    assert all(r["intent"] == "verification" for r in rows)
    assert all(r["dimension"] == "thread_watch" for r in rows)
    assert all(r["thread_id"] == "et-storage-0001" for r in rows)
    assert all(r["status"] == "active" for r in rows)
    assert all(r["created_at"] == "2026-05-30" for r in rows)


def test_seed_sources_deduplicates_registry_against_channels():
    from stratum.db.seed import _seed_sources

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _schema_for_sources(conn)

    _seed_sources(conn, {
        "channels": [{"id": "same", "url": "https://a.example.com", "type": "MEDIA"}],
        "source_registry": {
            "sources": [{"id": "same", "urls": ["https://b.example.com"], "category": "blog"}]
        },
    })

    rows = conn.execute("SELECT id, domain, type FROM sources").fetchall()
    assert len(rows) == 1
    assert rows[0]["domain"] == "a.example.com"
    assert rows[0]["type"] == "MEDIA"


def test_seed_queries_supports_dimension_grouped_strategy():
    from stratum.db.seed import _seed_queries

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            dimension TEXT DEFAULT 'general',
            include_domains TEXT,
            thread_id TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    """)

    _seed_queries(conn, {
        "queries": {
            "detection": {
                "platform_demand": {
                    "en": [
                        {
                            "id": "q-platform-en",
                            "text": "NVIDIA HBM demand",
                            "include_domains": ["nvidia.com", "developer.nvidia.com"],
                        },
                    ]
                }
            },
            "verification": {
                "financial": {
                    "zh-CN": [
                        "美光 财报 存储",
                    ]
                }
            },
        }
    })

    rows = [
        dict(row)
        for row in conn.execute("""
            SELECT id, text, locale, intent, dimension, include_domains, status
              FROM queries
             ORDER BY id
        """)
    ]
    for row in rows:
        row["include_domains"] = json.loads(row["include_domains"])

    assert rows == [
        {
            "id": "q-platform-en",
            "text": "NVIDIA HBM demand",
            "locale": "en",
            "intent": "detection",
            "dimension": "platform_demand",
            "include_domains": ["nvidia.com", "developer.nvidia.com"],
            "status": "active",
        },
        {
            "id": "q-verification-001",
            "text": "美光 财报 存储",
            "locale": "zh-CN",
            "intent": "verification",
            "dimension": "financial",
            "include_domains": [],
            "status": "active",
        },
    ]


def test_seed_queries_remains_compatible_without_dimension_column():
    from stratum.db.seed import _seed_queries

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            thread_id TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    """)

    _seed_queries(conn, {
        "queries": {
            "detection": {
                "technology": {
                    "en": ["Samsung HBM4"],
                }
            }
        }
    })

    row = conn.execute("SELECT id, text, locale, intent, status FROM queries").fetchone()
    assert dict(row) == {
        "id": "q-detection-000",
        "text": "Samsung HBM4",
        "locale": "en",
        "intent": "detection",
        "status": "active",
    }


def test_seed_queries_rejects_legacy_query_sections():
    from stratum.db.seed import _seed_queries
    import pytest

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    """)

    with pytest.raises(ValueError, match="structured queries"):
        _seed_queries(conn, {
            "seed_queries": {"en": ["Samsung HBM4"]},
            "gap_searches": ["Micron NAND"],
        })


def test_update_query_stats_accepts_search_subsystem_shape(monkeypatch, tmp_path):
    from stratum.db.ingest import update_query_stats

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            last_run TEXT,
            hit_count_7d INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        INSERT INTO queries (id, text, locale, intent, hit_count_7d)
        VALUES ('q-1', 'Samsung HBM4', 'en', 'detection', 2)
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    count = update_query_stats("storage", [
        {"query_id": "q-1", "results_count": 3, "status": "success"},
        {"query_id": "missing", "results_count": 9},
    ], run_date="2026-05-30")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT last_run, hit_count_7d FROM queries WHERE id = 'q-1'").fetchone()
    stat = check.execute(
        "SELECT results_count, status FROM query_run_stats WHERE query_id = 'q-1'"
    ).fetchone()
    check.close()
    assert count == 1
    assert row["last_run"] == "2026-05-30"
    assert row["hit_count_7d"] == 3
    assert stat["results_count"] == 3
    assert stat["status"] == "success"


def test_update_query_stats_is_idempotent_for_same_run_date(monkeypatch, tmp_path):
    from stratum.db.ingest import update_query_stats

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            last_run TEXT,
            hit_count_7d INTEGER DEFAULT 0
        );
        CREATE TABLE query_run_stats (
            query_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            results_count INTEGER DEFAULT 0,
            status TEXT,
            updated_at TEXT,
            PRIMARY KEY (query_id, run_date)
        );
    """)
    conn.execute("""
        INSERT INTO queries (id, text, locale, intent, hit_count_7d)
        VALUES ('q-1', 'Samsung HBM4', 'en', 'detection', 5)
    """)
    conn.execute("""
        INSERT INTO query_run_stats (query_id, run_date, results_count, status)
        VALUES ('q-1', '2026-05-30', 3, 'success')
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    update_query_stats(
        "storage",
        [{"query_id": "q-1", "results_count": 3, "status": "success"}],
        run_date="2026-05-30",
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT hit_count_7d FROM queries WHERE id = 'q-1'").fetchone()
    check.close()

    assert row["hit_count_7d"] == 3


def test_update_query_stats_applies_same_date_delta(monkeypatch, tmp_path):
    from stratum.db.ingest import update_query_stats

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            last_run TEXT,
            hit_count_7d INTEGER DEFAULT 0
        );
        CREATE TABLE query_run_stats (
            query_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            results_count INTEGER DEFAULT 0,
            status TEXT,
            updated_at TEXT,
            PRIMARY KEY (query_id, run_date)
        );
    """)
    conn.execute("""
        INSERT INTO queries (id, text, locale, intent, hit_count_7d)
        VALUES ('q-1', 'Samsung HBM4', 'en', 'detection', 5)
    """)
    conn.execute("""
        INSERT INTO query_run_stats (query_id, run_date, results_count, status)
        VALUES ('q-1', '2026-05-30', 3, 'success')
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    update_query_stats(
        "storage",
        [{"query_id": "q-1", "results_count": 1, "status": "success"}],
        run_date="2026-05-30",
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT hit_count_7d FROM queries WHERE id = 'q-1'").fetchone()
    stat = check.execute(
        "SELECT results_count FROM query_run_stats WHERE query_id = 'q-1'"
    ).fetchone()
    check.close()

    assert row["hit_count_7d"] == 1
    assert stat["results_count"] == 1


def test_update_query_stats_recomputes_query_rollups_from_ledger(monkeypatch, tmp_path):
    from stratum.db.ingest import update_query_stats

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            last_run TEXT,
            hit_count_7d INTEGER DEFAULT 0,
            hit_count_30d INTEGER DEFAULT 0,
            avg_articles REAL DEFAULT 0
        );
        CREATE TABLE query_run_stats (
            query_id TEXT NOT NULL,
            run_date TEXT NOT NULL,
            results_count INTEGER DEFAULT 0,
            status TEXT,
            updated_at TEXT,
            PRIMARY KEY (query_id, run_date)
        );
    """)
    conn.execute("""
        INSERT INTO queries (id, text, locale, intent, hit_count_7d, hit_count_30d, avg_articles)
        VALUES ('q-1', 'Samsung HBM4', 'en', 'detection', 999, 999, 999)
    """)
    conn.executemany("""
        INSERT INTO query_run_stats (query_id, run_date, results_count, status)
        VALUES ('q-1', ?, ?, 'success')
    """, [
        ("2026-04-30", 100),
        ("2026-05-21", 7),
        ("2026-05-24", 3),
    ])
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    update_query_stats(
        "storage",
        [{"query_id": "q-1", "results_count": 5, "status": "success"}],
        run_date="2026-05-30",
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("""
        SELECT hit_count_7d, hit_count_30d, avg_articles
        FROM queries WHERE id = 'q-1'
    """).fetchone()
    check.close()

    assert row["hit_count_7d"] == 8
    assert row["hit_count_30d"] == 15
    assert row["avg_articles"] == 5


def test_get_queries_for_scale_preserves_dimension(monkeypatch, tmp_path):
    from stratum.db.ingest import get_queries_for_scale

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            status TEXT
        );
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            dimension TEXT DEFAULT 'general',
            include_domains TEXT,
            thread_id TEXT,
            status TEXT DEFAULT 'active'
        );
        INSERT INTO queries (id, text, locale, intent, dimension, include_domains, status)
        VALUES (
            'q-tech',
            'Samsung HBM4',
            'en',
            'detection',
            'technology',
            '["semiconductor.samsung.com", "news.samsung.com"]',
            'active'
        );
    """)
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    rows = get_queries_for_scale("storage", "daily")
    assert rows == [{
        "id": "q-tech",
        "text": "Samsung HBM4",
        "locale": "en",
        "intent": "detection",
        "dimension": "technology",
        "include_domains": ["semiconductor.samsung.com", "news.samsung.com"],
    }]


def test_get_queries_for_scale_daily_includes_cooling_thread_watch_queries(monkeypatch, tmp_path):
    from stratum.db.ingest import get_queries_for_scale

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            status TEXT
        );
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT NOT NULL,
            intent TEXT NOT NULL,
            dimension TEXT DEFAULT 'general',
            thread_id TEXT,
            status TEXT DEFAULT 'active'
        );
        INSERT INTO threads (id, status)
        VALUES
            ('et-cooling', 'cooling'),
            ('et-resolved', 'resolved');
        INSERT INTO queries (id, text, locale, intent, dimension, thread_id, status)
        VALUES
            ('q-watch-cooling', 'Samsung HBM4 follow up', 'en', 'verification', 'thread_watch', 'et-cooling', 'active'),
            ('q-watch-resolved', 'Old resolved story', 'en', 'verification', 'thread_watch', 'et-resolved', 'active');
    """)
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    rows = get_queries_for_scale("storage", "daily")

    assert rows == [{
        "id": "q-watch-cooling",
        "text": "Samsung HBM4 follow up",
        "locale": "en",
        "intent": "verification",
        "dimension": "thread_watch",
    }]


def test_ingest_daily_events_does_not_recount_existing_daily_event(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_daily_events

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'emerging',
            priority INTEGER DEFAULT 3,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER DEFAULT 0
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            scale TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT,
            article_ids TEXT,
            entity_ids TEXT,
            term_ids TEXT,
            source_domains TEXT,
            confidence TEXT,
            briefing_id TEXT,
            created_at TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE thread_entities (
            thread_id TEXT,
            entity_id TEXT,
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE causal_edges (
            id TEXT PRIMARY KEY,
            cause_thread_id TEXT,
            effect_thread_id TEXT,
            mechanism TEXT,
            confidence TEXT,
            scale TEXT,
            source_briefing TEXT,
            verified INTEGER,
            verified_at TEXT,
            verified_by_scale TEXT,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT PRIMARY KEY,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            scale TEXT,
            source_briefing TEXT,
            result TEXT,
            verified_at TEXT,
            verified_by_scale TEXT,
            actual_outcome TEXT,
            created_at TEXT
        );
    """)
    conn.execute("""
        INSERT INTO threads
            (id, label, status, priority, first_event_date, last_event_date, event_count_daily)
        VALUES ('et-1', 'Samsung HBM4', 'active', 2, '2026-05-30', '2026-05-30', 1)
    """)
    conn.execute("""
        INSERT INTO events
            (id, thread_id, scale, date, title, article_ids, entity_ids, term_ids,
             source_domains, confidence, briefing_id, created_at, status, priority)
        VALUES
            ('ev-2026-05-30-et-1', 'et-1', 'daily', '2026-05-30', 'Old title',
             '[]', '[]', '[]', '[]', 'B', 'daily-2026-05-30', '2026-05-30T00:00:00',
             'active', 2)
    """)
    conn.commit()
    conn.close()

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [{
            "thread_id": "et-1",
            "title": "Updated Samsung HBM4",
            "status": "active",
            "priority": 2,
            "entity_ids": ["samsung"],
        }]
    }))

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    stats = ingest_daily_events(str(event_threads), "storage", "2026-05-30")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    thread = check.execute("SELECT event_count_daily FROM threads WHERE id = 'et-1'").fetchone()
    event = check.execute("SELECT title FROM events WHERE id = 'ev-2026-05-30-et-1'").fetchone()
    check.close()

    assert stats["events"] == 1
    assert thread["event_count_daily"] == 1
    assert event["title"] == "Updated Samsung HBM4"


def test_ingest_daily_events_counts_new_daily_event_once(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_daily_events

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'emerging',
            priority INTEGER DEFAULT 3,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER DEFAULT 0
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            scale TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT,
            article_ids TEXT,
            entity_ids TEXT,
            term_ids TEXT,
            source_domains TEXT,
            confidence TEXT,
            briefing_id TEXT,
            created_at TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE thread_entities (
            thread_id TEXT,
            entity_id TEXT,
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE causal_edges (
            id TEXT PRIMARY KEY,
            cause_thread_id TEXT,
            effect_thread_id TEXT,
            mechanism TEXT,
            confidence TEXT,
            scale TEXT,
            source_briefing TEXT,
            verified INTEGER,
            verified_at TEXT,
            verified_by_scale TEXT,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT PRIMARY KEY,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            scale TEXT,
            source_briefing TEXT,
            result TEXT,
            verified_at TEXT,
            verified_by_scale TEXT,
            actual_outcome TEXT,
            created_at TEXT
        );
    """)
    conn.execute("""
        INSERT INTO threads
            (id, label, status, priority, first_event_date, last_event_date, event_count_daily)
        VALUES ('et-1', 'Samsung HBM4', 'active', 2, '2026-05-29', '2026-05-29', 1)
    """)
    conn.commit()
    conn.close()

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [{
            "thread_id": "et-1",
            "title": "Samsung HBM4 follow-up",
            "status": "active",
            "priority": 2,
        }]
    }))

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    ingest_daily_events(str(event_threads), "storage", "2026-05-30")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    thread = check.execute("SELECT event_count_daily FROM threads WHERE id = 'et-1'").fetchone()
    check.close()

    assert thread["event_count_daily"] == 2


def test_ingest_daily_events_normalizes_label_priorities(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_daily_events

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'emerging',
            priority INTEGER DEFAULT 3,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER DEFAULT 0
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            scale TEXT NOT NULL,
            date TEXT,
            title TEXT,
            article_ids TEXT,
            entity_ids TEXT,
            term_ids TEXT,
            source_domains TEXT,
            confidence TEXT,
            briefing_id TEXT,
            created_at TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE thread_entities (
            thread_id TEXT,
            entity_id TEXT,
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE causal_edges (
            id TEXT PRIMARY KEY,
            cause_thread_id TEXT,
            effect_thread_id TEXT,
            mechanism TEXT,
            confidence TEXT,
            scale TEXT,
            source_briefing TEXT,
            verified INTEGER,
            verified_at TEXT,
            verified_by_scale TEXT,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT PRIMARY KEY,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            scale TEXT,
            source_briefing TEXT,
            result TEXT,
            verified_at TEXT,
            verified_by_scale TEXT,
            actual_outcome TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [{
            "thread_id": "et-priority",
            "title": "Priority-normalized thread",
            "status": "active",
            "priority": "high",
        }]
    }))

    ingest_daily_events(str(event_threads), "storage", "2026-05-30")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    thread = check.execute("SELECT priority FROM threads WHERE id = 'et-priority'").fetchone()
    event = check.execute("SELECT priority FROM events WHERE id = 'ev-2026-05-30-et-priority'").fetchone()
    check.close()

    assert thread["priority"] == 1
    assert event["priority"] == 1

    event_threads.write_text(json.dumps({
        "threads": [{
            "thread_id": "et-priority",
            "title": "Priority-normalized thread",
            "status": "cooling",
            "priority": "low",
        }]
    }))

    ingest_daily_events(str(event_threads), "storage", "2026-05-31")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    thread = check.execute("SELECT priority FROM threads WHERE id = 'et-priority'").fetchone()
    event = check.execute("SELECT priority FROM events WHERE id = 'ev-2026-05-31-et-priority'").fetchone()
    check.close()

    assert thread["priority"] == 3
    assert event["priority"] == 3


def test_ingest_daily_events_rebuilds_thread_entities_from_events(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_daily_events

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'emerging',
            priority INTEGER DEFAULT 3,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER DEFAULT 0
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            scale TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT,
            article_ids TEXT,
            entity_ids TEXT,
            term_ids TEXT,
            source_domains TEXT,
            confidence TEXT,
            briefing_id TEXT,
            created_at TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE thread_entities (
            thread_id TEXT,
            entity_id TEXT,
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE causal_edges (
            id TEXT PRIMARY KEY,
            cause_thread_id TEXT,
            effect_thread_id TEXT,
            mechanism TEXT,
            confidence TEXT,
            scale TEXT,
            source_briefing TEXT,
            verified INTEGER,
            verified_at TEXT,
            verified_by_scale TEXT,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT PRIMARY KEY,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            scale TEXT,
            source_briefing TEXT,
            result TEXT,
            verified_at TEXT,
            verified_by_scale TEXT,
            actual_outcome TEXT,
            created_at TEXT
        );
    """)
    conn.execute("""
        INSERT INTO threads
            (id, label, status, priority, first_event_date, last_event_date, event_count_daily)
        VALUES ('et-1', 'Samsung HBM4', 'active', 2, '2026-05-29', '2026-05-30', 2)
    """)
    conn.execute("""
        INSERT INTO events
            (id, thread_id, scale, date, title, article_ids, entity_ids, term_ids,
             source_domains, confidence, briefing_id, created_at, status, priority)
        VALUES
            ('ev-2026-05-29-et-1', 'et-1', 'daily', '2026-05-29', 'Historic event',
             '[]', '["micron"]', '[]', '[]', 'B', 'daily-2026-05-29',
             '2026-05-29T00:00:00', 'active', 2),
            ('ev-2026-05-30-et-1', 'et-1', 'daily', '2026-05-30', 'Old event',
             '[]', '["sk-hynix"]', '[]', '[]', 'B', 'daily-2026-05-30',
             '2026-05-30T00:00:00', 'active', 2)
    """)
    conn.execute("INSERT INTO thread_entities VALUES ('et-1', 'micron', 'subject')")
    conn.execute("INSERT INTO thread_entities VALUES ('et-1', 'sk-hynix', 'subject')")
    conn.commit()
    conn.close()

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [{
            "thread_id": "et-1",
            "title": "Corrected event",
            "status": "active",
            "priority": 2,
            "entity_ids": ["samsung"],
        }]
    }))

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    ingest_daily_events(str(event_threads), "storage", "2026-05-30")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    entities = [
        row["entity_id"]
        for row in check.execute(
            "SELECT entity_id FROM thread_entities WHERE thread_id = 'et-1' ORDER BY entity_id"
        )
    ]
    check.close()

    assert entities == ["micron", "samsung"]


def test_ingest_daily_events_removes_stale_pending_edges_and_judgments(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_daily_events

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'emerging',
            priority INTEGER DEFAULT 3,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER DEFAULT 0
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            scale TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT,
            article_ids TEXT,
            entity_ids TEXT,
            term_ids TEXT,
            source_domains TEXT,
            confidence TEXT,
            briefing_id TEXT,
            created_at TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE thread_entities (
            thread_id TEXT,
            entity_id TEXT,
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE causal_edges (
            id TEXT PRIMARY KEY,
            cause_thread_id TEXT,
            effect_thread_id TEXT,
            mechanism TEXT,
            confidence TEXT,
            scale TEXT,
            source_briefing TEXT,
            verified INTEGER,
            verified_at TEXT,
            verified_by_scale TEXT,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT PRIMARY KEY,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            scale TEXT,
            source_briefing TEXT,
            result TEXT,
            verified_at TEXT,
            verified_by_scale TEXT,
            actual_outcome TEXT,
            created_at TEXT
        );
    """)
    conn.execute("""
        INSERT INTO causal_edges
            (id, cause_thread_id, effect_thread_id, mechanism, confidence, scale,
             source_briefing, created_at)
        VALUES ('ce-old', 'et-a', 'et-b', 'stale', 'B', 'daily', 'daily-2026-05-30',
                '2026-05-30T00:00:00')
    """)
    conn.execute("""
        INSERT INTO judgments
            (id, target_type, target_entity_ids, target_thread_ids, hypothesis, confidence,
             expected_verification, scale, source_briefing, result, created_at)
        VALUES ('jd-old', 'entity', '["samsung"]', '[]', 'stale', 'B', '2026-06-01',
                'daily', 'daily-2026-05-30', 'pending', '2026-05-30T00:00:00')
    """)
    conn.commit()
    conn.close()

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [],
        "causal_edges": [{
            "id": "ce-new",
            "cause_thread_id": "et-a",
            "effect_thread_id": "et-c",
            "mechanism": "updated",
        }],
        "judgments": [{
            "id": "jd-new",
            "target_type": "entity",
            "target_entity_ids": ["micron"],
            "hypothesis": "updated",
        }],
    }))

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    ingest_daily_events(str(event_threads), "storage", "2026-05-30")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    edges = [row["id"] for row in check.execute("SELECT id FROM causal_edges ORDER BY id")]
    judgments = [row["id"] for row in check.execute("SELECT id FROM judgments ORDER BY id")]
    check.close()

    assert edges == ["ce-new"]
    assert judgments == ["jd-new"]


def test_ingest_daily_events_skips_unknown_thread_entities_with_fk(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_daily_events

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE entities (id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'emerging',
            priority INTEGER DEFAULT 3,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER DEFAULT 0
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES threads(id),
            scale TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT,
            article_ids TEXT,
            entity_ids TEXT,
            term_ids TEXT,
            source_domains TEXT,
            confidence TEXT,
            briefing_id TEXT,
            created_at TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE thread_entities (
            thread_id TEXT REFERENCES threads(id),
            entity_id TEXT REFERENCES entities(id),
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE causal_edges (
            id TEXT PRIMARY KEY,
            cause_thread_id TEXT REFERENCES threads(id),
            effect_thread_id TEXT REFERENCES threads(id),
            mechanism TEXT,
            confidence TEXT,
            scale TEXT,
            source_briefing TEXT,
            verified INTEGER,
            verified_at TEXT,
            verified_by_scale TEXT,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT PRIMARY KEY,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            scale TEXT,
            source_briefing TEXT,
            result TEXT,
            verified_at TEXT,
            verified_by_scale TEXT,
            actual_outcome TEXT,
            created_at TEXT
        );
    """)
    conn.execute("INSERT INTO entities (id, status) VALUES ('samsung', 'active')")
    conn.commit()
    conn.close()

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [{
            "thread_id": "et-1",
            "title": "Samsung and new entity update",
            "entity_ids": ["samsung", "New_Entity"],
        }],
    }))

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    stats = ingest_daily_events(str(event_threads), "storage", "2026-05-30")

    check = sqlite3.connect(db_path)
    entities = [
        row[0]
        for row in check.execute(
            "SELECT entity_id FROM thread_entities WHERE thread_id = 'et-1'"
        )
    ]
    check.close()

    assert stats["errors"] == []
    assert entities == ["samsung"]


def test_ingest_daily_events_preserves_verification_fields_on_replace(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_daily_events

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'emerging',
            priority INTEGER DEFAULT 3,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER DEFAULT 0
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            scale TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT,
            article_ids TEXT,
            entity_ids TEXT,
            term_ids TEXT,
            source_domains TEXT,
            confidence TEXT,
            briefing_id TEXT,
            created_at TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE thread_entities (
            thread_id TEXT,
            entity_id TEXT,
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE causal_edges (
            id TEXT PRIMARY KEY,
            cause_thread_id TEXT,
            effect_thread_id TEXT,
            mechanism TEXT,
            confidence TEXT,
            scale TEXT,
            source_briefing TEXT,
            verified INTEGER,
            verified_at TEXT,
            verified_by_scale TEXT,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT PRIMARY KEY,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            scale TEXT,
            source_briefing TEXT,
            result TEXT,
            verified_at TEXT,
            verified_by_scale TEXT,
            actual_outcome TEXT,
            created_at TEXT
        );
    """)
    conn.execute("""
        INSERT INTO causal_edges
            (id, cause_thread_id, effect_thread_id, mechanism, confidence, scale,
             source_briefing, verified, verified_at, verified_by_scale, created_at)
        VALUES ('ce-keep', 'et-a', 'et-b', 'old', 'B', 'daily', 'daily-2026-05-30',
                1, '2026-06-01', 'weekly', '2026-05-30T00:00:00')
    """)
    conn.execute("""
        INSERT INTO judgments
            (id, target_type, target_entity_ids, target_thread_ids, hypothesis, confidence,
             expected_verification, scale, source_briefing, result, verified_at,
             verified_by_scale, actual_outcome, created_at)
        VALUES ('jd-keep', 'entity', '["samsung"]', '[]', 'old', 'B', '2026-06-01',
                'daily', 'daily-2026-05-30', 'correct', '2026-06-01', 'weekly',
                'confirmed', '2026-05-30T00:00:00')
    """)
    conn.commit()
    conn.close()

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [],
        "causal_edges": [{
            "id": "ce-keep",
            "cause_thread_id": "et-a",
            "effect_thread_id": "et-c",
            "mechanism": "new",
        }],
        "judgments": [{
            "id": "jd-keep",
            "target_type": "entity",
            "target_entity_ids": ["micron"],
            "hypothesis": "new",
        }],
    }))

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    ingest_daily_events(str(event_threads), "storage", "2026-05-30")

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    edge = check.execute("SELECT mechanism, verified, verified_at FROM causal_edges").fetchone()
    judgment = check.execute(
        "SELECT hypothesis, result, verified_at, actual_outcome FROM judgments"
    ).fetchone()
    check.close()

    assert edge["mechanism"] == "new"
    assert edge["verified"] == 1
    assert edge["verified_at"] == "2026-06-01"
    assert judgment["hypothesis"] == "new"
    assert judgment["result"] == "correct"
    assert judgment["verified_at"] == "2026-06-01"
    assert judgment["actual_outcome"] == "confirmed"


def test_ingest_entity_snapshots_uses_article_counts(monkeypatch, tmp_path):
    from stratum.db.ingest import ingest_entity_snapshots

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE thread_entities (
            thread_id TEXT,
            entity_id TEXT,
            role TEXT DEFAULT 'subject',
            PRIMARY KEY (thread_id, entity_id)
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            scale TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT
        );
        CREATE TABLE entity_snapshots (
            entity_id TEXT,
            scale TEXT NOT NULL,
            period TEXT NOT NULL,
            status TEXT,
            key_events TEXT,
            article_count INTEGER,
            thread_ids TEXT,
            importance_delta REAL,
            summary TEXT,
            PRIMARY KEY (entity_id, scale, period)
        );
    """)
    conn.execute("INSERT INTO entities (id, status) VALUES ('samsung', 'active')")
    conn.execute("INSERT INTO entities (id, status) VALUES ('micron', 'active')")
    conn.execute("INSERT INTO thread_entities (thread_id, entity_id) VALUES ('et-1', 'samsung')")
    conn.execute("""
        INSERT INTO events (id, thread_id, scale, date, title)
        VALUES ('ev-1', 'et-1', 'daily', '2026-05-30', 'Samsung HBM4 update')
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    count = ingest_entity_snapshots(
        "storage",
        "daily",
        "2026-05-30",
        {"samsung": 3},
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    rows = {
        row["entity_id"]: dict(row)
        for row in check.execute("SELECT entity_id, article_count, key_events FROM entity_snapshots")
    }
    check.close()

    assert count == 2
    assert rows["samsung"]["article_count"] == 3
    assert rows["micron"]["article_count"] == 0
    assert "Samsung HBM4 update" in rows["samsung"]["key_events"]


def test_update_entities_after_run_counts_only_existing_entities(monkeypatch, tmp_path):
    from stratum.db.ingest import update_entities_after_run

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            last_seen TEXT,
            article_count_7d INTEGER DEFAULT 0
        )
    """)
    conn.execute("INSERT INTO entities (id, article_count_7d) VALUES ('samsung', 2)")
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    count = update_entities_after_run("storage", [
        {"id": "samsung", "article_count_today": 3},
        {"id": "missing", "article_count_today": 9},
    ])

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute(
        "SELECT last_seen, article_count_7d FROM entities WHERE id = 'samsung'"
    ).fetchone()
    check.close()

    assert count == 1
    assert row["last_seen"]
    assert row["article_count_7d"] == 5


def test_update_entities_after_run_uses_pipeline_run_date(monkeypatch, tmp_path):
    from stratum.db.ingest import update_entities_after_run

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            last_seen TEXT,
            article_count_7d INTEGER DEFAULT 0
        )
    """)
    conn.execute("INSERT INTO entities (id, article_count_7d) VALUES ('samsung', 0)")
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    update_entities_after_run(
        "storage",
        [{"id": "samsung", "article_count_today": 1}],
        run_date="2026-05-01",
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT last_seen FROM entities WHERE id = 'samsung'").fetchone()
    check.close()

    assert row["last_seen"] == "2026-05-01"


def test_update_entities_after_run_is_idempotent_for_same_period(monkeypatch, tmp_path):
    from stratum.db.ingest import update_entities_after_run

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            last_seen TEXT,
            article_count_7d INTEGER DEFAULT 0
        );
        CREATE TABLE entity_snapshots (
            entity_id TEXT,
            scale TEXT NOT NULL,
            period TEXT NOT NULL,
            article_count INTEGER,
            PRIMARY KEY (entity_id, scale, period)
        );
    """)
    conn.execute("INSERT INTO entities (id, article_count_7d) VALUES ('samsung', 10)")
    conn.execute("""
        INSERT INTO entity_snapshots (entity_id, scale, period, article_count)
        VALUES ('samsung', 'daily', '2026-05-30', 3)
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    update_entities_after_run(
        "storage",
        [{"id": "samsung", "article_count_today": 3}],
        run_date="2026-05-30",
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute(
        "SELECT last_seen, article_count_7d FROM entities WHERE id = 'samsung'"
    ).fetchone()
    check.close()

    assert row["last_seen"] == "2026-05-30"
    assert row["article_count_7d"] == 3


def test_update_entities_after_run_applies_same_period_delta(monkeypatch, tmp_path):
    from stratum.db.ingest import update_entities_after_run

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            last_seen TEXT,
            article_count_7d INTEGER DEFAULT 0
        );
        CREATE TABLE entity_snapshots (
            entity_id TEXT,
            scale TEXT NOT NULL,
            period TEXT NOT NULL,
            article_count INTEGER,
            PRIMARY KEY (entity_id, scale, period)
        );
    """)
    conn.execute("INSERT INTO entities (id, article_count_7d) VALUES ('samsung', 10)")
    conn.execute("""
        INSERT INTO entity_snapshots (entity_id, scale, period, article_count)
        VALUES ('samsung', 'daily', '2026-05-30', 3)
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    update_entities_after_run(
        "storage",
        [{"id": "samsung", "article_count_today": 5}],
        run_date="2026-05-30",
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("SELECT article_count_7d FROM entities WHERE id = 'samsung'").fetchone()
    check.close()

    assert row["article_count_7d"] == 5


def test_update_entities_after_run_recomputes_rollups_from_snapshots(monkeypatch, tmp_path):
    from stratum.db.ingest import update_entities_after_run

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            last_seen TEXT,
            article_count_7d INTEGER DEFAULT 0,
            article_count_30d INTEGER DEFAULT 0
        );
        CREATE TABLE entity_snapshots (
            entity_id TEXT,
            scale TEXT NOT NULL,
            period TEXT NOT NULL,
            article_count INTEGER,
            PRIMARY KEY (entity_id, scale, period)
        );
    """)
    conn.execute("""
        INSERT INTO entities (id, article_count_7d, article_count_30d)
        VALUES ('samsung', 999, 999)
    """)
    conn.executemany("""
        INSERT INTO entity_snapshots (entity_id, scale, period, article_count)
        VALUES ('samsung', 'daily', ?, ?)
    """, [
        ("2026-04-30", 100),
        ("2026-05-21", 7),
        ("2026-05-24", 3),
    ])
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)

    update_entities_after_run(
        "storage",
        [{"id": "samsung", "article_count_today": 5}],
        run_date="2026-05-30",
    )

    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    row = check.execute("""
        SELECT article_count_7d, article_count_30d
        FROM entities WHERE id = 'samsung'
    """).fetchone()
    snapshot = check.execute("""
        SELECT article_count FROM entity_snapshots
        WHERE entity_id = 'samsung' AND scale = 'daily' AND period = '2026-05-30'
    """).fetchone()
    check.close()

    assert row["article_count_7d"] == 8
    assert row["article_count_30d"] == 15
    assert snapshot["article_count"] == 5
