"""Tests for the database consumption service layer."""

from __future__ import annotations

import json
import sqlite3


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _patch_get_db(monkeypatch, db_path):
    def fake_get_db(domain):
        return _connect(db_path)

    monkeypatch.setattr("stratum.db.service.get_db", fake_get_db)


def _make_service_db(path, include_reports=False):
    conn = _connect(path)
    conn.executescript(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            label TEXT,
            description TEXT,
            status TEXT,
            priority INTEGER,
            first_event_date TEXT,
            last_event_date TEXT,
            event_count_daily INTEGER,
            event_count_weekly INTEGER,
            parent_thread_id TEXT
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
        CREATE TABLE entity_snapshots (
            entity_id TEXT,
            scale TEXT,
            period TEXT,
            status TEXT,
            key_events TEXT,
            article_count INTEGER,
            thread_ids TEXT,
            importance_delta REAL,
            summary TEXT,
            PRIMARY KEY (entity_id, scale, period)
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO threads (
            id, label, description, status, priority, first_event_date,
            last_event_date, event_count_daily, event_count_weekly, parent_thread_id
        )
        VALUES (?, ?, '', 'active', ?, ?, ?, 1, 0, NULL)
        """,
        [
            ("et-hbm", "HBM race", 1, "2026-05-25", "2026-05-30"),
            ("et-nand", "NAND pricing", 2, "2026-05-28", "2026-05-29"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO events (
            id, thread_id, scale, date, title, article_ids, entity_ids,
            term_ids, source_domains, confidence, briefing_id, created_at,
            status, priority
        )
        VALUES (?, ?, 'daily', ?, ?, ?, ?, ?, ?, 'B', ?, ?, 'active', ?)
        """,
        [
            (
                "ev-2026-05-30-et-hbm",
                "et-hbm",
                "2026-05-30",
                "Samsung HBM4 qualification advances",
                json.dumps(["a-1"]),
                json.dumps(["samsung"]),
                json.dumps(["hbm"]),
                json.dumps(["example.com"]),
                "daily-2026-05-30",
                "2026-05-30T08:00:00+08:00",
                1,
            ),
            (
                "ev-2026-05-29-et-nand",
                "et-nand",
                "2026-05-29",
                "NAND prices rise",
                json.dumps(["a-2"]),
                json.dumps(["samsung", "sk-hynix"]),
                json.dumps(["nand"]),
                json.dumps(["example.kr"]),
                "daily-2026-05-29",
                "2026-05-29T08:00:00+08:00",
                2,
            ),
        ],
    )
    conn.execute(
        """
        INSERT INTO judgments (
            id, target_type, target_entity_ids, target_thread_ids, hypothesis,
            confidence, expected_verification, scale, source_briefing, result,
            created_at
        )
        VALUES (
            'jd-1', 'entity', '["samsung"]', '["et-hbm"]',
            'Samsung remains in HBM qualification window', 'B',
            'check next week', 'daily', 'daily-2026-05-30', NULL,
            '2026-05-30T08:00:00+08:00'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO causal_edges (
            id, cause_thread_id, effect_thread_id, mechanism, confidence,
            scale, source_briefing, verified, created_at
        )
        VALUES (
            'ce-1', 'et-hbm', 'et-nand', 'AI demand pulls memory supply',
            'B', 'daily', 'daily-2026-05-30', NULL,
            '2026-05-30T08:00:00+08:00'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO entity_snapshots (
            entity_id, scale, period, status, key_events, article_count,
            thread_ids, importance_delta, summary
        )
        VALUES (
            'samsung', 'daily', '2026-05-30', 'active',
            '["Samsung HBM4 qualification advances"]', 1,
            '["et-hbm"]', 0, ''
        )
        """
    )

    if include_reports:
        conn.executescript(
            """
            CREATE TABLE reports (
                id TEXT PRIMARY KEY,
                domain TEXT,
                scale TEXT,
                period TEXT,
                markdown_path TEXT
            );
            CREATE TABLE report_sections (
                id TEXT PRIMARY KEY,
                report_id TEXT,
                section_key TEXT,
                title TEXT,
                position INTEGER
            );
            CREATE TABLE report_items (
                id TEXT PRIMARY KEY,
                report_id TEXT,
                section_id TEXT,
                position INTEGER,
                title TEXT,
                body TEXT
            );
            CREATE TABLE report_item_events (
                report_item_id TEXT,
                event_id TEXT
            );
            CREATE TABLE articles (
                id TEXT PRIMARY KEY,
                title TEXT,
                url TEXT,
                source TEXT,
                published_at TEXT,
                snippet TEXT,
                domain TEXT NOT NULL
            );
            CREATE TABLE report_item_articles (
                report_item_id TEXT,
                article_id TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO reports VALUES ('r-daily-2026-05-30', 'storage', 'daily', '2026-05-30', '/tmp/report.md')"
        )
        conn.execute(
            "INSERT INTO report_sections VALUES ('sec-1', 'r-daily-2026-05-30', 'today', '今日要点', 1)"
        )
        conn.execute(
            "INSERT INTO report_items VALUES ('item-1', 'r-daily-2026-05-30', 'sec-1', 1, 'HBM update', 'Body')"
        )
        conn.execute("INSERT INTO report_item_events VALUES ('item-1', 'ev-2026-05-30-et-hbm')")
        conn.execute(
            "INSERT INTO articles VALUES ('a-1', 'Samsung article', 'https://example.com/a', 'Example', '2026-05-30', 'Snippet', 'storage')"
        )
        conn.execute("INSERT INTO report_item_articles VALUES ('item-1', 'a-1')")

    conn.commit()
    conn.close()


def test_report_context_degrades_without_report_tables(monkeypatch, tmp_path):
    from stratum.db.service import get_report_context

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    context = get_report_context("storage", "daily", "2026-05-30")

    assert context["report"] is None
    assert context["sections"] == []
    assert context["items"] == []
    assert [event["id"] for event in context["events"]] == ["ev-2026-05-30-et-hbm"]
    assert context["events"][0]["article_ids"] == ["a-1"]
    assert [j["id"] for j in context["judgments"]] == ["jd-1"]
    assert [edge["id"] for edge in context["causal_edges"]] == ["ce-1"]


def test_report_context_reads_report_tables_when_present(monkeypatch, tmp_path):
    from stratum.db.service import get_report_context

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path, include_reports=True)
    _patch_get_db(monkeypatch, db_path)

    context = get_report_context("storage", "daily", "2026-05-30")

    assert context["report"]["id"] == "r-daily-2026-05-30"
    assert [section["title"] for section in context["sections"]] == ["今日要点"]
    assert [item["title"] for item in context["items"]] == ["HBM update"]


def test_cascade_inputs_assemble_weekly_window(monkeypatch, tmp_path):
    from stratum.db.service import get_cascade_inputs

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    inputs = get_cascade_inputs("storage", "weekly", "2026-W22")

    assert inputs["source_scale"] == "daily"
    assert inputs["source_scales"] == ["daily"]
    assert inputs["window"] == {"start": "2026-05-25", "end": "2026-05-31"}
    assert [event["id"] for event in inputs["events"]] == [
        "ev-2026-05-29-et-nand",
        "ev-2026-05-30-et-hbm",
    ]
    assert [j["id"] for j in inputs["due_judgments"]] == ["jd-1"]


def test_cascade_inputs_exclude_judgments_due_after_window(monkeypatch, tmp_path):
    from stratum.db.service import get_cascade_inputs

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO judgments (
            id, target_type, target_entity_ids, target_thread_ids, hypothesis,
            confidence, expected_verification, scale, source_briefing, result,
            created_at
        )
        VALUES (
            'jd-future', 'entity', '["samsung"]', '["et-hbm"]',
            'Samsung result should be checked later', 'B',
            '2026-06-15', 'daily', 'daily-2026-05-30', NULL,
            '2026-05-30T08:00:00+08:00'
        )
        """
    )
    conn.commit()
    conn.close()
    _patch_get_db(monkeypatch, db_path)

    inputs = get_cascade_inputs("storage", "weekly", "2026-W22")

    assert [j["id"] for j in inputs["due_judgments"]] == ["jd-1"]


def test_cascade_inputs_include_deferred_judgments_when_due(monkeypatch, tmp_path):
    from stratum.db.service import get_cascade_inputs

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO judgments (
            id, target_type, target_entity_ids, target_thread_ids, hypothesis,
            confidence, expected_verification, scale, source_briefing, result,
            created_at
        )
        VALUES (
            'jd-deferred', 'entity', '["samsung"]', '["et-hbm"]',
            'Samsung result should be checked after deferral', 'B',
            '2026-05-30', 'daily', 'daily-2026-05-30', 'deferred',
            '2026-05-30T08:00:00+08:00'
        )
        """
    )
    conn.commit()
    conn.close()
    _patch_get_db(monkeypatch, db_path)

    inputs = get_cascade_inputs("storage", "weekly", "2026-W22")

    assert [j["id"] for j in inputs["due_judgments"]] == ["jd-1", "jd-deferred"]


def test_cascade_inputs_support_custom_window(monkeypatch, tmp_path):
    from stratum.db.service import get_cascade_inputs

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    inputs = get_cascade_inputs(
        "storage",
        "monthly",
        window_start="2026-05-30",
        window_end="2026-05-30",
    )

    assert inputs["target_period"] == "custom-2026-05-30_to_2026-05-30"
    assert inputs["window"] == {"start": "2026-05-30", "end": "2026-05-30"}
    assert inputs["report_window"]["period_kind"] == "custom_range"
    assert [event["id"] for event in inputs["events"]] == ["ev-2026-05-30-et-hbm"]


def test_entity_and_technology_tracking(monkeypatch, tmp_path):
    from stratum.db.service import get_entity_timeline, get_technology_progress

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    entity = get_entity_timeline("storage", "samsung", scale="daily")
    progress = get_technology_progress("storage", "hbm", entity_ids=["samsung", "sk-hynix"])

    assert [snapshot["period"] for snapshot in entity["snapshots"]] == ["2026-05-30"]
    assert [event["id"] for event in entity["events"]] == [
        "ev-2026-05-29-et-nand",
        "ev-2026-05-30-et-hbm",
    ]
    assert list(progress) == ["samsung"]
    assert progress["samsung"][0]["title"] == "Samsung HBM4 qualification advances"


def test_report_item_evidence_is_forward_compatible(monkeypatch, tmp_path):
    from stratum.db.service import get_report_item_evidence

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path, include_reports=True)
    _patch_get_db(monkeypatch, db_path)

    evidence = get_report_item_evidence("storage", "item-1")

    assert evidence["item"]["title"] == "HBM update"
    assert [event["id"] for event in evidence["events"]] == ["ev-2026-05-30-et-hbm"]
    assert [article["id"] for article in evidence["articles"]] == ["a-1"]


def test_evidence_detail_read_model_builds_report_item_payload():
    from stratum.db.semantic_reads import EvidenceDetailReadModel

    evidence = EvidenceDetailReadModel().report_item_evidence(
        report_item_id="item-1",
        item={"id": "item-1", "title": "HBM update"},
        events=[{"id": "ev-1"}],
        articles=[{"id": "a-1"}],
    )

    assert evidence == {
        "report_item_id": "item-1",
        "item": {"id": "item-1", "title": "HBM update"},
        "events": [{"id": "ev-1"}],
        "articles": [{"id": "a-1"}],
    }


def test_tracking_read_model_filters_and_groups_events():
    from stratum.db.semantic_reads import TrackingReadModel

    model = TrackingReadModel()
    events = [
        {"id": "ev-1", "entity_ids": ["samsung"], "term_ids": ["hbm"]},
        {"id": "ev-2", "entity_ids": ["sk-hynix"], "term_ids": ["hbm"]},
        {"id": "ev-3", "entity_ids": ["samsung", "micron"], "term_ids": ["nand"]},
    ]

    filtered = model.filter_json_member(events, column="entity_ids", member_id="samsung", order="ASC")
    progress = model.technology_progress(term_id="hbm", events=events[:2], entity_ids=["samsung"])
    timeline = model.entity_timeline(entity_id="samsung", snapshots=[{"period": "2026-05-30"}], events=filtered)

    assert [event["id"] for event in filtered] == ["ev-1", "ev-3"]
    assert progress == {"samsung": [events[0]]}
    assert timeline["entity_id"] == "samsung"
    assert [event["id"] for event in timeline["events"]] == ["ev-1", "ev-3"]


def test_trend_read_model_builds_ranked_summary():
    from stratum.db.semantic_reads import TrendReadModel

    model = TrendReadModel()
    events = [
        {
            "id": "ev-b",
            "thread_id": "thread-b",
            "date": "2026-05-29",
            "title": "B",
            "entity_ids": ["samsung"],
            "term_ids": ["nand"],
            "priority": 2,
        },
        {
            "id": "ev-a",
            "thread_id": "thread-a",
            "date": "2026-05-30",
            "title": "A",
            "entity_ids": ["samsung", "sk-hynix"],
            "term_ids": ["hbm"],
            "priority": 1,
        },
        {
            "id": "ev-c",
            "thread_id": "thread-a",
            "date": "2026-05-30",
            "title": "C",
            "entity_ids": ["sk-hynix"],
            "term_ids": ["hbm"],
            "priority": 3,
        },
    ]
    judgments = [{"id": "jd-1", "result": None}, {"id": "jd-2", "result": "supported"}]

    summary = model.trend_summary(
        domain="storage",
        scale="daily",
        start_period="2026-05-29",
        end_period="2026-05-30",
        events=events,
        judgments=judgments,
    )

    assert summary["event_count"] == 3
    assert summary["top_threads"] == [{"id": "thread-a", "count": 2}, {"id": "thread-b", "count": 1}]
    assert summary["top_entities"] == [{"id": "samsung", "count": 2}, {"id": "sk-hynix", "count": 2}]
    assert summary["judgment_counts"] == {"pending": 1, "supported": 1}
    assert [event["id"] for event in summary["key_events"]] == ["ev-a", "ev-b", "ev-c"]


def test_judgment_status_read_model_groups_pending_results():
    from stratum.db.semantic_reads import JudgmentStatusReadModel

    model = JudgmentStatusReadModel()
    status = model.status(
        domain="storage",
        scale="daily",
        start_period="2026-05-29",
        end_period="2026-05-30",
        judgments=[
            {"id": "jd-pending", "result": ""},
            {"id": "jd-supported", "result": "supported"},
            {"id": "jd-pending-2", "result": None},
        ],
    )

    assert status["counts"] == {"pending": 2, "supported": 1}
    assert [judgment["id"] for judgment in status["judgments"]["pending"]] == ["jd-pending", "jd-pending-2"]


def test_key_timeline_groups_events_by_date(monkeypatch, tmp_path):
    from stratum.db.service import get_key_timeline

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    timeline = get_key_timeline("storage", "daily", "2026-05-29", "2026-05-30")

    assert [entry["period"] for entry in timeline] == ["2026-05-29", "2026-05-30"]
    assert timeline[0]["titles"] == ["NAND prices rise"]
    assert timeline[1]["titles"] == ["Samsung HBM4 qualification advances"]


def test_trend_summary_and_key_events_delegate_semantic_read_model(monkeypatch, tmp_path):
    from stratum.db.service import get_key_events, get_trend_summary

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    summary = get_trend_summary("storage", "daily", "2026-05-29", "2026-05-30")
    key_events = get_key_events("storage", "daily", "2026-05-29", "2026-05-30", limit=1)

    assert summary["event_count"] == 2
    assert summary["top_entities"] == [{"id": "samsung", "count": 2}, {"id": "sk-hynix", "count": 1}]
    assert summary["judgment_counts"] == {"pending": 1}
    assert [event["id"] for event in key_events] == ["ev-2026-05-30-et-hbm"]


def test_load_latest_search_engine_health_from_path(tmp_path):
    from stratum.db.service import load_latest_search_engine_health_from_path

    db_path = tmp_path / "storage.db"
    conn = _connect(db_path)
    conn.execute("""
        CREATE TABLE search_engine_health (
            engine TEXT NOT NULL,
            run_date TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            successes INTEGER DEFAULT 0,
            no_results INTEGER DEFAULT 0,
            failures INTEGER DEFAULT 0,
            rate_limited INTEGER DEFAULT 0,
            not_configured INTEGER DEFAULT 0,
            unsupported INTEGER DEFAULT 0,
            health_score REAL DEFAULT 0,
            failure_rate REAL DEFAULT 0,
            recommendation TEXT,
            errors TEXT,
            updated_at TEXT,
            PRIMARY KEY (engine, run_date)
        )
    """)
    conn.executemany(
        """
        INSERT INTO search_engine_health (
            engine, run_date, attempts, successes, no_results, failures,
            rate_limited, not_configured, unsupported, health_score,
            failure_rate, recommendation, errors, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("tavily", "2026-05-29", 3, 3, 0, 0, 0, 0, 0, 1.0, 0.0, "healthy", "[]", "now"),
            ("tavily", "2026-05-30", 2, 0, 0, 2, 1, 0, 0, 0.0, 1.0, "avoid", '["quota"]', "now"),
            ("bocha", "2026-05-30", 1, 1, 0, 0, 0, 0, 0, 1.0, 0.0, "healthy", "[]", "now"),
        ],
    )
    conn.commit()
    conn.close()

    health = load_latest_search_engine_health_from_path(str(db_path))

    assert health["tavily"]["run_date"] == "2026-05-30"
    assert health["tavily"]["recommendation"] == "avoid"
    assert health["tavily"]["errors"] == ["quota"]
    assert health["bocha"]["recommendation"] == "healthy"
