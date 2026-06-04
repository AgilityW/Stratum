"""Capability-layer regression tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stratum.subsystems.event_thread import EventThread, TimelineEntry
from stratum.subsystems.story_tracking import CausalEdge, EventRecord, Judgment


def test_capabilities_package_exports_stable_surfaces():
    import stratum.capabilities as capabilities

    assert "source_trace" in capabilities.__all__
    assert "signal_bursts" in capabilities.__all__
    assert "signal_awareness" in capabilities.__all__
    assert "discovery_diagnostics" in capabilities.__all__
    assert "evaluate_reports" in capabilities.__all__
    assert "source_expansion" in capabilities.__all__
    assert "watch_queries" in capabilities.__all__
    assert "attach_signal" in capabilities.__all__
    assert "thread_timeline" in capabilities.__all__
    assert "thread_keywords" in capabilities.__all__
    assert "entity_timeline" in capabilities.__all__
    assert "technology_progress" in capabilities.__all__
    assert "trend_summary" in capabilities.__all__
    assert "key_events" in capabilities.__all__
    assert "key_timeline" in capabilities.__all__
    assert "judgment_status" in capabilities.__all__
    assert "due_judgments" in capabilities.__all__
    assert "active_queries" in capabilities.__all__
    assert "search_health_db" in capabilities.__all__
    assert "search_health" in capabilities.__all__
    assert "report_evidence" in capabilities.__all__
    assert "report_lineage" in capabilities.__all__
    assert "cascade_inputs" in capabilities.__all__
    assert "briefing_context" in capabilities.__all__
    assert "format_briefing" in capabilities.__all__
    assert "thread_lifecycle" in capabilities.__all__
    assert "synthesis_policy" in capabilities.__all__
    assert "report_context" in capabilities.__all__
    assert "story_context" in capabilities.__all__
    assert "awareness_config" in capabilities.__all__
    assert "list_capabilities" in capabilities.__all__
    assert "describe" in capabilities.__all__
    assert "list_calls" in capabilities.__all__
    assert "call" in capabilities.__all__
    assert "list_tasks" in capabilities.__all__
    assert "get_task" in capabilities.__all__
    assert "run_task" in capabilities.__all__


def test_signal_awareness_capability_loads_domain_config():
    from stratum.capabilities import awareness_config

    cfg = awareness_config("storage")
    assert cfg["topic_rules"]
    assert cfg["anchors"]


def test_source_trace_capability_runs_from_data_dir(tmp_path):
    from stratum.capabilities import source_trace

    (tmp_path / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"HBM4"}\n'
    )
    (tmp_path / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","url":"https://example.com/a","title":"HBM4","status":"accept","accepted":true}\n'
    )
    (tmp_path / "watchlist_results.json").write_text(json.dumps([
        {"source": "feed-a", "url": "https://example.com/a", "title": "HBM4"}
    ]))
    (tmp_path / "raw.json").write_text(json.dumps([
        {"source": "feed-a", "url": "https://example.com/a", "title": "HBM4"}
    ]))

    payload = source_trace(input_dir=str(tmp_path))

    assert payload["source_trace_summary"]["status"] == "ok"
    assert payload["source_quality"][0]["source"] == "feed-a"


def test_signal_bursts_capability_can_bootstrap_from_data_dir(tmp_path):
    from stratum.capabilities import signal_bursts

    (tmp_path / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","source_type_hint":"official","url":"https://example.com/a","title":"HBM4 qualification for NVIDIA","published_at":"2026-06-03"}\n'
    )
    (tmp_path / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","source_type_hint":"official","url":"https://example.com/a","title":"HBM4 qualification for NVIDIA","status":"accept","accepted":true,"published_at":"2026-06-03"}\n'
    )
    (tmp_path / "watchlist_results.json").write_text(json.dumps([
        {"source": "feed-a", "source_type_hint": "official", "url": "https://example.com/a", "title": "HBM4 qualification for NVIDIA", "published_at": "2026-06-03"}
    ]))
    (tmp_path / "raw.json").write_text(json.dumps([
        {"source": "feed-a", "source_type_hint": "official", "url": "https://example.com/a", "title": "HBM4 qualification for NVIDIA", "published_at": "2026-06-03"}
    ]))

    payload = signal_bursts(
        terms=["HBM4", "NVIDIA", "qualification"],
        data_dir=str(tmp_path),
        run_date="2026-06-03",
    )

    assert payload["diagnostics"]["matched_terms"] >= 2
    assert payload["bursts"]


def test_signal_awareness_capability_runs_with_domain_config():
    from stratum.capabilities import (
        awareness_config,
        signal_awareness,
    )

    cfg = awareness_config("storage")
    payload = signal_awareness(
        domain="storage",
        run_date="2026-06-03",
        records=[
            {
                "source": "feed-a",
                "source_type_hint": "media",
                "title": "Computex 2026 preview highlights SSD vendors in Taipei",
                "snippet": "Booth and keynote preview for storage vendors",
                "entities": ["Phison", "Silicon Motion"],
            }
        ],
        topic_rules=cfg["topic_rules"],
        anchor_registry=cfg["anchors"],
    )

    assert payload["domain"] == "storage"
    assert "activation_plan" in payload


def test_capability_registry_and_runtime_surfaces_are_mcp_ready():
    from stratum.capabilities import (
        describe,
        call,
        list_capabilities,
        list_calls,
    )

    names = {item["name"] for item in list_capabilities()}
    assert "source_trace.run" in names
    assert "signal_bursts.run" in names
    assert "signal_awareness.run" in names
    assert "discovery_diagnostics.build" in names
    assert "report_evaluation.run" in names
    assert "source_expansion.evaluate" in names
    assert "watch_queries.generate" in names
    assert "signal_aware_daily.attach" in names
    assert "thread_timeline.get" in names
    assert "thread_keyword_events.get" in names
    assert "entity_timeline.get" in names
    assert "technology_progress.get" in names
    assert "trend_summary.get" in names
    assert "key_events.get" in names
    assert "key_timeline.get" in names
    assert "judgment_status.get" in names
    assert "due_judgments.get" in names
    assert "active_search_queries.load" in names
    assert "search_engine_health.load" in names
    assert "search_engine_health.get" in names
    assert "report_item_evidence.get" in names
    assert "report_lineage.trace" in names
    assert "cascade_inputs.get" in names
    assert "briefing_context.generate" in names
    assert "briefing_context.format" in names
    assert "thread_lifecycle.diagnostics" in names
    assert "synthesis_policy_config.get" in names
    assert "report_context.get" in list_calls()

    descriptor = describe("source_trace.run")
    assert descriptor["owner"] == "stratum.source_trace"

    result = call("does.not.exist", {})
    assert result["status"] == "error"
    assert result["error"]["type"] == "UnknownCapability"


def test_collection_diagnostic_capabilities_and_agent_tasks_work(tmp_path):
    from stratum.capabilities import get_task, call, run_task

    workspace = str(Path(__file__).resolve().parents[1])
    diagnostics = call(
        "discovery_diagnostics.build",
        {
            "domain": "storage",
            "workspace": workspace,
            "queries": [
                {
                    "id": "q-1",
                    "text": "HBM4 qualification",
                    "locale": "en",
                    "intent": "detection",
                    "dimension": "product",
                    "include_domains": ["example.com"],
                }
            ],
            "raw_results": [
                {
                    "url": "https://example.com/hbm4",
                    "title": "HBM4 qualification update",
                    "snippet": "Vendor qualification update",
                    "locale": "en",
                    "published_at": "2026-06-03",
                    "source_domain": "example.com",
                    "source_type_hint": "media",
                    "engine": "tavily",
                    "query_id": "q-1",
                    "query_dimension": "product",
                }
            ],
            "curated_results": [
                {
                    "url": "https://example.com/hbm4",
                    "title": "HBM4 qualification update",
                    "snippet": "Vendor qualification update",
                    "locale": "en",
                    "published_at": "2026-06-03",
                    "source_domain": "example.com",
                    "source_type_hint": "media",
                    "engine": "tavily",
                    "query_id": "q-1",
                    "query_dimension": "product",
                }
            ],
            "query_stats": [
                {
                    "query_id": "q-1",
                    "engine_used": "tavily",
                    "status": "success",
                    "results_count": 1,
                    "locale": "en",
                    "intent": "detection",
                    "dimension": "product",
                    "query_text": "HBM4 qualification",
                    "include_domains": ["example.com"],
                }
            ],
        },
    )
    assert diagnostics["status"] == "ok"
    assert any(
        row["locale"] == "en"
        for row in diagnostics["payload"]["locale_coverage"]
    )
    assert "engine_health" in diagnostics["payload"]

    descriptor = get_task("inspect_discovery_diagnostics")
    assert "discovery_diagnostics.build" in descriptor["capabilities"]

    (tmp_path / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","engine":"rss:feed-a","url":"https://example.com/a","title":"HBM4 update","published_at":"2026-06-03","access":"rss"}\n'
    )
    (tmp_path / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","engine":"rss:feed-a","url":"https://example.com/a","title":"HBM4 update","published_at":"2026-06-03","accepted":true,"access":"rss"}\n'
    )
    (tmp_path / "watchlist_results.json").write_text(json.dumps([
        {"source": "feed-a", "engine": "rss:feed-a", "url": "https://example.com/a", "title": "HBM4 update", "published_at": "2026-06-03", "access": "rss"}
    ]))
    (tmp_path / "raw.json").write_text(json.dumps([
        {"source": "feed-a", "engine": "rss:feed-a", "url": "https://example.com/a", "title": "HBM4 update", "published_at": "2026-06-03", "access": "rss"}
    ]))

    expansion = call(
        "source_expansion.evaluate",
        {"run_data_dir": str(tmp_path)},
    )
    assert expansion["status"] == "ok"
    assert expansion["payload"]["sources"][0]["source"] == "feed-a"

    task = run_task(
        "inspect_source_expansion",
        {"run_data_dir": str(tmp_path)},
    )
    assert task["status"] == "ok"
    assert task["result"]["totals"]["sources"] == 1


def test_agent_task_can_compose_signal_landscape_from_run_dir(tmp_path):
    from stratum.capabilities import get_task, run_task

    (tmp_path / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","source_type_hint":"official","url":"https://example.com/a","title":"Computex 2026 HBM4 qualification for NVIDIA in Taipei","snippet":"Storage vendors preview Taipei event","published_at":"2026-06-03"}\n'
    )
    (tmp_path / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","source_type_hint":"official","url":"https://example.com/a","title":"Computex 2026 HBM4 qualification for NVIDIA in Taipei","snippet":"Storage vendors preview Taipei event","status":"accept","accepted":true,"published_at":"2026-06-03"}\n'
    )
    (tmp_path / "watchlist_results.json").write_text(json.dumps([
        {
            "source": "feed-a",
            "source_type_hint": "official",
            "url": "https://example.com/a",
            "title": "Computex 2026 HBM4 qualification for NVIDIA in Taipei",
            "snippet": "Storage vendors preview Taipei event",
            "published_at": "2026-06-03"
        }
    ]))
    (tmp_path / "raw.json").write_text(json.dumps([
        {
            "source": "feed-a",
            "source_type_hint": "official",
            "url": "https://example.com/a",
            "title": "Computex 2026 HBM4 qualification for NVIDIA in Taipei",
            "snippet": "Storage vendors preview Taipei event",
            "published_at": "2026-06-03"
        }
    ]))

    descriptor = get_task("analyze_signal_landscape")
    assert "source_trace.run" in descriptor["capabilities"]

    result = run_task("analyze_signal_landscape", {
        "domain": "storage",
        "data_dir": str(tmp_path),
        "run_date": "2026-06-03",
        "terms": ["HBM4", "NVIDIA", "Computex 2026"],
    })

    assert result["status"] == "ok"
    assert len(result["steps"]) == 3
    assert result["result"]["source_trace"]["source_trace_summary"]["status"] == "ok"
    assert result["result"]["signal_bursts"]["diagnostics"]["matched_terms"] >= 2
    assert result["result"]["signal_awareness"]["domain"] == "storage"


def test_evaluation_and_watch_query_capabilities_work_through_runtime(tmp_path):
    from stratum.capabilities import call

    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps({
        "cases": [
            {
                "id": "case-1",
                "scale": "daily",
                "domain": "storage",
                "report_markdown": "Micron cites HBM demand. Source: Micron.",
                "expectations": {
                    "required_phrases": ["HBM demand"],
                    "required_sources": ["Micron"],
                    "min_score": 1.0
                }
            }
        ]
    }))

    evaluation = call("report_evaluation.run", {
        "cases_path": str(cases_path),
    })
    assert evaluation["status"] == "ok"
    assert evaluation["payload"]["passed_cases"] == 1

    queries = call("watch_queries.generate", {
        "threads": {
            "thread-a": EventThread(
                id="thread-a",
                title="HBM4 qualification",
                canonical_question="HBM4 qualification",
                status="active",
                priority="high",
                created="2026-06-03",
                last_updated="2026-06-03",
                watch_signals=["HBM4 qualification NVIDIA"],
                timeline=[
                    TimelineEntry(
                        date="2026-06-03",
                        cluster_id="sc-1",
                        update_type="first_disclosure",
                        summary="HBM4 qualification",
                        confidence_after="B",
                    )
                ],
            )
        },
        "locales": ["en", "zh-CN"],
    })
    assert queries["status"] == "ok"
    assert len(queries["payload"]) == 2


def test_attach_signal_awareness_capability_uses_existing_run(tmp_path):
    from stratum.capabilities import call

    output_root = tmp_path / "runtime"
    reports_dir = output_root / "Reports"
    data_dir = reports_dir / "storage" / "data" / "2026-06-03"
    data_dir.mkdir(parents=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f'output_dir: "{output_root}"\n')
    (data_dir / "watchlist_observations.jsonl").write_text(
        '{"source":"feed-a","source_type_hint":"media","url":"https://example.com/a","title":"Computex 2026 storage preview in Taipei","snippet":"Storage vendor preview","published_at":"2026-06-03"}\n'
    )
    (data_dir / "watchlist_candidates.jsonl").write_text(
        '{"source":"feed-a","source_type_hint":"media","url":"https://example.com/a","title":"Computex 2026 storage preview in Taipei","snippet":"Storage vendor preview","status":"accept","accepted":true,"published_at":"2026-06-03"}\n'
    )
    (data_dir / "watchlist_results.json").write_text(json.dumps([
        {"source": "feed-a", "source_type_hint": "media", "url": "https://example.com/a", "title": "Computex 2026 storage preview in Taipei", "snippet": "Storage vendor preview", "published_at": "2026-06-03"}
    ]))
    (data_dir / "raw.json").write_text(json.dumps([
        {"source": "feed-a", "source_type_hint": "media", "url": "https://example.com/a", "title": "Computex 2026 storage preview in Taipei", "snippet": "Storage vendor preview", "published_at": "2026-06-03"}
    ]))

    result = call("signal_aware_daily.attach", {
        "domain": "storage",
        "run_date": "2026-06-03",
        "config_path": str(config_path),
    })

    assert result["status"] == "ok"
    assert result["payload"]["payload"]["domain"] == "storage"
    assert (data_dir / "signal_awareness.json").exists()
    assert (data_dir / "signal_plan.json").exists()


def test_db_read_capabilities_and_agent_tasks_work_with_service_db(monkeypatch, tmp_path):
    from stratum.capabilities import get_task, call, run_task

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path)
    _patch_get_db(monkeypatch, db_path)

    thread_timeline = call("thread_timeline.get", {
        "domain": "storage",
        "thread_id": "et-hbm",
    })
    assert thread_timeline["status"] == "ok"
    assert thread_timeline["payload"][0]["id"] == "ev-2026-05-30-et-hbm"

    thread_keyword_events = call("thread_keyword_events.get", {
        "domain": "storage",
    })
    assert thread_keyword_events["status"] == "ok"
    assert thread_keyword_events["payload"][0]["thread_id"] == "et-hbm"

    entity_timeline = call("entity_timeline.get", {
        "domain": "storage",
        "entity_id": "samsung",
        "scale": "daily",
    })
    assert entity_timeline["status"] == "ok"
    assert entity_timeline["payload"]["snapshots"][0]["period"] == "2026-05-30"

    technology_progress = call("technology_progress.get", {
        "domain": "storage",
        "term_id": "hbm",
        "entity_ids": ["samsung", "sk-hynix"],
    })
    assert technology_progress["status"] == "ok"
    assert list(technology_progress["payload"]) == ["samsung"]

    trend_summary = call("trend_summary.get", {
        "domain": "storage",
        "scale": "daily",
        "start_period": "2026-05-29",
        "end_period": "2026-05-30",
    })
    assert trend_summary["status"] == "ok"

    key_timeline = call("key_timeline.get", {
        "domain": "storage",
        "scale": "daily",
        "start_period": "2026-05-29",
        "end_period": "2026-05-30",
    })
    assert key_timeline["status"] == "ok"
    assert key_timeline["payload"]

    judgment_status = call("judgment_status.get", {
        "domain": "storage",
        "scale": "daily",
        "start_period": "2026-05-29",
        "end_period": "2026-05-30",
    })
    assert judgment_status["status"] == "ok"

    due_judgments = call("due_judgments.get", {
        "domain": "storage",
        "scale": "daily",
        "period": "2026-05-30",
    })
    assert due_judgments["status"] == "ok"
    assert due_judgments["payload"][0]["id"] == "jd-1"

    key_events = call("key_events.get", {
        "domain": "storage",
        "scale": "daily",
        "start_period": "2026-05-29",
        "end_period": "2026-05-30",
    })
    assert key_events["status"] == "ok"
    assert key_events["payload"]

    descriptor = get_task("inspect_scale_trends")
    assert "trend_summary.get" in descriptor["capabilities"]

    task = run_task("inspect_scale_trends", {
        "domain": "storage",
        "scale": "daily",
        "start_period": "2026-05-29",
        "end_period": "2026-05-30",
    })
    assert task["status"] == "ok"
    assert "trend_summary" in task["result"]


def test_report_lineage_and_cascade_input_capabilities_work_with_service_db(monkeypatch, tmp_path):
    from stratum.capabilities import call, run_task

    db_path = tmp_path / "storage.db"
    _make_service_db(db_path, include_reports=True)
    _patch_get_db(monkeypatch, db_path)

    lineage = call("report_lineage.trace", {
        "domain": "storage",
        "report_id": "r-daily-2026-05-30",
    })
    assert lineage["status"] == "ok"
    assert lineage["payload"]["report"]["id"] == "r-daily-2026-05-30"

    evidence = call("report_item_evidence.get", {
        "domain": "storage",
        "report_item_id": "item-1",
    })
    assert evidence["status"] == "ok"
    assert evidence["payload"]["item"]["title"] == "HBM update"

    cascade = call("cascade_inputs.get", {
        "domain": "storage",
        "target_scale": "weekly",
        "target_period": "2026-W22",
    })
    assert cascade["status"] == "ok"
    assert cascade["payload"]["source_scale"] == "daily"

    task = run_task("prepare_scale_synthesis_research", {
        "domain": "storage",
        "target_scale": "weekly",
        "target_period": "2026-W22",
    })
    assert task["status"] == "ok"
    assert task["result"]["source_scale"] == "daily"


def test_search_query_and_engine_health_capabilities_work_with_db_paths(monkeypatch, tmp_path):
    from stratum.capabilities import call, run_task

    db_path = tmp_path / "search.db"
    conn = _connect(db_path)
    conn.executescript(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            status TEXT
        );
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT,
            locale TEXT,
            intent TEXT,
            dimension TEXT,
            include_domains TEXT,
            status TEXT,
            thread_id TEXT
        );
        CREATE TABLE search_engine_health (
            engine TEXT,
            run_date TEXT,
            attempts INTEGER,
            successes INTEGER,
            no_results INTEGER,
            failures INTEGER,
            rate_limited INTEGER,
            not_configured INTEGER,
            unsupported INTEGER,
            health_score REAL,
            failure_rate REAL,
            recommendation TEXT,
            errors TEXT
        );
        """
    )
    conn.execute("INSERT INTO threads VALUES ('thread-1', 'active')")
    conn.execute(
        "INSERT INTO queries VALUES ('q-1', 'HBM4', 'en', 'detection', 'technology', '[\"example.com\"]', 'active', 'thread-1')"
    )
    conn.execute(
        "INSERT INTO search_engine_health VALUES ('tavily', '2026-06-03', 10, 8, 1, 1, 0, 0, 0, 0.8, 0.1, 'keep', '[\"timeout\"]')"
    )
    conn.commit()
    conn.close()

    queries = call("active_search_queries.load", {
        "db_path": str(db_path),
    })
    assert queries["status"] == "ok"
    assert queries["payload"][0]["id"] == "q-1"

    health = call("search_engine_health.load", {
        "db_path": str(db_path),
    })
    assert health["status"] == "ok"
    assert health["payload"]["tavily"]["attempts"] == 10

    task = run_task("inspect_active_search_queries", {
        "db_path": str(db_path),
    })
    assert task["status"] == "ok"
    assert task["result"][0]["id"] == "q-1"

    task = run_task("inspect_search_engine_health", {
        "db_path": str(db_path),
    })
    assert task["status"] == "ok"
    assert task["result"]["tavily"]["health_score"] == 0.8


def test_research_context_and_diagnostics_capabilities_work():
    from stratum.capabilities import get_task, call, run_task

    events = [
        EventRecord(
            id="event-storage-0001",
            title="HBM update",
            canonical_question="Who leads HBM?",
            created="2026-06-01",
            last_updated="2026-06-03",
            entity_tags=["Samsung"],
            status="active",
            priority=1,
        )
    ]
    edges = [
        CausalEdge(
            id="causal-storage-0001",
            cause_id="event-storage-0001",
            effect_id="event-storage-0002",
            mechanism="HBM demand drives packaging pressure",
            confidence="B",
            created="2026-06-03",
        )
    ]
    judgments = [
        Judgment(
            id="judgment-storage-0001",
            target_type="entity",
            target_ids=["Samsung"],
            hypothesis="Samsung remains in the HBM qualification window",
            confidence="B",
            made_at="2026-06-01",
            expected_verification="2026-06-05",
        )
    ]
    thread = EventThread(
        id="et-storage-0001",
        title="HBM",
        canonical_question="Who leads HBM?",
        status="active",
        priority="high",
        created="2026-06-01",
        last_updated="2026-06-03",
        timeline=[
            TimelineEntry(
                date="2026-06-03",
                cluster_id="sc-1",
                update_type="first_disclosure",
                summary="HBM update",
                confidence_after="B",
            )
        ],
    )

    briefing = call("briefing_context.generate", {
        "domain_id": "storage",
        "scale": "daily",
        "target_date": "2026-06-04",
        "events": events,
        "edges": edges,
        "judgments": judgments,
    })
    assert briefing["status"] == "ok"
    assert briefing["payload"]["domain_id"] == "storage"

    lifecycle = call("thread_lifecycle.diagnostics", {
        "threads": {"et-storage-0001": thread},
        "run_date": "2026-06-04",
    })
    assert lifecycle["status"] == "ok"
    assert lifecycle["payload"][0]["thread_id"] == "et-storage-0001"

    synthesis_policy = call("synthesis_policy_config.get", {
        "target_scale": "weekly",
    })
    assert synthesis_policy["status"] == "ok"
    assert synthesis_policy["payload"]["target_scale"] == "weekly"

    descriptor = get_task("prepare_briefing_context")
    assert "briefing_context.generate" in descriptor["capabilities"]

    task = run_task("prepare_briefing_context", {
        "domain_id": "storage",
        "scale": "daily",
        "target_date": "2026-06-04",
        "events": events,
        "edges": edges,
        "judgments": judgments,
    })
    assert task["status"] == "ok"
    assert "Briefing Context" in task["result"]["prompt_block"]


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
