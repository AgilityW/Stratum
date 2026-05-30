"""Tests for DB timeline read helpers."""

from __future__ import annotations

import json
import sqlite3


def _make_events_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
        )
    """)
    rows = [
        {
            "id": "ev-1",
            "thread_id": "et-hbm",
            "scale": "daily",
            "date": "2026-05-30",
            "title": "Samsung HBM4 qualification advances",
            "article_ids": ["a-1"],
            "entity_ids": ["samsung"],
            "term_ids": ["hbm"],
            "source_domains": ["example.com"],
            "priority": 1,
        },
        {
            "id": "ev-2",
            "thread_id": "et-hbm",
            "scale": "daily",
            "date": "2026-05-29",
            "title": "SK hynix expands HBM capacity",
            "article_ids": ["a-2"],
            "entity_ids": ["sk-hynix"],
            "term_ids": ["hbm"],
            "source_domains": ["example.kr"],
            "priority": 2,
        },
        {
            "id": "ev-3",
            "thread_id": "et-nand",
            "scale": "daily",
            "date": "2026-01-15",
            "title": "Samsung NAND pricing update",
            "article_ids": ["a-3"],
            "entity_ids": ["samsung"],
            "term_ids": ["nand"],
            "source_domains": ["example.cn"],
            "priority": 3,
        },
    ]
    for row in rows:
        conn.execute(
            """
            INSERT INTO events (
                id, thread_id, scale, date, title, article_ids, entity_ids,
                term_ids, source_domains, confidence, briefing_id, created_at,
                status, priority
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'B', '', '', 'active', ?)
            """,
            (
                row["id"],
                row["thread_id"],
                row["scale"],
                row["date"],
                row["title"],
                json.dumps(row["article_ids"]),
                json.dumps(row["entity_ids"]),
                json.dumps(row["term_ids"]),
                json.dumps(row["source_domains"]),
                row["priority"],
            ),
        )
    conn.commit()
    conn.close()


def _patch_get_db(monkeypatch, db_path):
    def fake_get_db(domain):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("stratum.db.ingest.get_db", fake_get_db)


def test_get_entity_events_filters_date_range_and_parses_json(monkeypatch, tmp_path):
    from stratum.db.ingest import get_entity_events

    db_path = tmp_path / "storage.db"
    _make_events_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    events = get_entity_events(
        "storage",
        "samsung",
        start_date="2026-05-01",
        end_date="2026-05-30",
    )

    assert [event["id"] for event in events] == ["ev-1"]
    assert events[0]["article_ids"] == ["a-1"]
    assert events[0]["entity_ids"] == ["samsung"]
    assert events[0]["term_ids"] == ["hbm"]


def test_get_term_events_returns_topic_history(monkeypatch, tmp_path):
    from stratum.db.ingest import get_term_events

    db_path = tmp_path / "storage.db"
    _make_events_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    events = get_term_events("storage", "hbm", start_date="2026-05-01", order="asc")

    assert [event["id"] for event in events] == ["ev-2", "ev-1"]


def test_get_term_company_progress_groups_events_by_entity(monkeypatch, tmp_path):
    from stratum.db.ingest import get_term_company_progress

    db_path = tmp_path / "storage.db"
    _make_events_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    progress = get_term_company_progress(
        "storage",
        "hbm",
        entity_ids=["samsung", "sk-hynix", "micron"],
        start_date="2026-05-01",
    )

    assert set(progress) == {"samsung", "sk-hynix"}
    assert [event["title"] for event in progress["samsung"]] == [
        "Samsung HBM4 qualification advances"
    ]
    assert [event["title"] for event in progress["sk-hynix"]] == [
        "SK hynix expands HBM capacity"
    ]
