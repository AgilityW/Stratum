"""Regression tests for orchestrator helper behavior."""

import json
import os
import sqlite3
import sys
from pathlib import Path
import pytest


def test_export_thread_keywords_has_regex_available(tmp_path, monkeypatch):
    """Exporting thread keywords should write tokens instead of swallowing NameError."""
    from stratum.orchestrator import pipeline
    from stratum.db import service

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE events (id TEXT, thread_id TEXT, title TEXT, entity_ids TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
        ("evt-1", "et-storage-0001", "Samsung HBM4量产", json.dumps(["samsung"]), "active"),
    )
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        assert domain == "storage"
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr(service, "get_db", fake_get_db)
    out_path = tmp_path / "thread_keywords.json"

    pipeline._export_thread_keywords("storage", {"thread_keywords": str(out_path)})

    data = json.loads(out_path.read_text())
    assert data["threads"][0]["thread_id"] == "et-storage-0001"
    assert "samsung" in data["threads"][0]["keywords"]


def test_export_thread_keywords_aggregates_events_by_thread(tmp_path, monkeypatch):
    """One continuing story should export one keyword profile, not one per event."""
    from stratum.orchestrator import pipeline
    from stratum.db import service

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE events (id TEXT, thread_id TEXT, title TEXT, entity_ids TEXT, status TEXT)"
    )
    conn.executemany(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
        [
            (
                "evt-1",
                "et-storage-0001",
                "Samsung HBM4量产",
                json.dumps(["samsung", "hbm4"]),
                "cooling",
            ),
            (
                "evt-2",
                "et-storage-0001",
                "SK hynix HBM4供应",
                json.dumps(["sk-hynix", "hbm4"]),
                "active",
            ),
        ],
    )
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        assert domain == "storage"
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr(service, "get_db", fake_get_db)
    out_path = tmp_path / "thread_keywords.json"

    pipeline._export_thread_keywords("storage", {"thread_keywords": str(out_path)})

    data = json.loads(out_path.read_text())
    assert len(data["threads"]) == 1
    thread = data["threads"][0]
    assert thread["thread_id"] == "et-storage-0001"
    assert thread["status"] == "active"
    assert {"samsung", "sk-hynix", "hbm4"}.issubset(set(thread["keywords"]))


def test_browser_watchlist_reports_missing_playwright(monkeypatch):
    from stratum.sourcing.watchlist import browser

    monkeypatch.setattr(browser, "find_spec", lambda name: None)

    try:
        browser.ensure_browser_available()
    except browser.BrowserWatchlistUnavailable as exc:
        assert "pip install -e '.[browser]'" in str(exc)
    else:
        raise AssertionError("expected BrowserWatchlistUnavailable")


def test_from_stage_resume_gates_pipeline_steps():
    from stratum.orchestrator.pipeline import should_run_stage

    assert should_run_stage(None, "search")
    assert should_run_stage("cluster", "cluster")
    assert should_run_stage("cluster", "edit")
    assert should_run_stage("cluster", "render")
    assert not should_run_stage("cluster", "search")
    assert not should_run_stage("cluster", "normalize")
    assert not should_run_stage("render", "validate")
    assert should_run_stage("render", "render")


def test_from_stage_resume_rejects_unknown_stage():
    from stratum.orchestrator.pipeline import should_run_stage

    with pytest.raises(ValueError, match="Unknown pipeline stage"):
        should_run_stage("typo", "render")

    with pytest.raises(ValueError, match="Unknown pipeline stage"):
        should_run_stage("render", "typo")


def test_resolve_paths_uses_render_artifact_basename(tmp_path):
    from stratum.orchestrator.pipeline import resolve_paths

    paths = resolve_paths("ai-storage", "2026-05-30", str(tmp_path))

    assert paths["briefing_html"].endswith(
        "Ai_storage_Daily_Briefing_2026-05-30.html"
    )
    assert paths["briefing_pdf"].endswith(
        "Ai_storage_Daily_Briefing_2026-05-30.pdf"
    )
    assert paths["briefing_md"].endswith(
        "Ai_storage_Daily_Briefing_2026-05-30.md"
    )
    assert paths["verify_stats"].endswith("verified.stats.json")


def test_resolve_paths_supports_higher_scale_artifacts(tmp_path):
    from stratum.orchestrator.pipeline import resolve_paths

    paths = resolve_paths("storage", "2026-W22", str(tmp_path), "weekly")

    assert paths["data_dir"].endswith("storage/data/weekly/2026-W22")
    assert paths["briefing_md"].endswith("Storage_Weekly_Briefing_2026-W22.md")
    assert paths["briefing_html"].endswith("Storage_Weekly_Briefing_2026-W22.html")
    assert paths["briefing_pdf"].endswith("Storage_Weekly_Briefing_2026-W22.pdf")


def test_runtime_dirs_keep_reports_and_database_roots_separate(tmp_path):
    from stratum.orchestrator.run_context import resolve_runtime_dirs

    roots = resolve_runtime_dirs({"output_dir": str(tmp_path / "workspace")})

    assert roots.output_dir == str(tmp_path / "workspace")
    assert roots.reports_dir == str(tmp_path / "workspace" / "Reports")
    assert roots.db_dir == str(tmp_path / "workspace" / "DataBase")
    assert roots.health_data_dir == str(tmp_path / "workspace" / "health-data")


def test_runtime_dirs_reject_same_reports_and_database_root(tmp_path):
    from stratum.orchestrator.run_context import resolve_runtime_dirs

    shared = str(tmp_path / "shared")
    with pytest.raises(ValueError, match="reports_dir and db_dir"):
        resolve_runtime_dirs({
            "output_dir": str(tmp_path / "workspace"),
            "reports_dir": shared,
            "db_dir": shared,
        })


def test_report_window_resolves_standard_and_custom_periods():
    from stratum.contracts.report_window import resolve_report_window

    standard = resolve_report_window("monthly", "2026-05")
    custom = resolve_report_window(
        "monthly",
        None,
        start_date="2026-05-01",
        end_date="2026-07-31",
    )

    assert standard.to_dict() == {
        "scale": "monthly",
        "period": "2026-05",
        "start": "2026-05-01",
        "end": "2026-05-31",
        "period_kind": "standard",
        "label": "2026-05",
    }
    assert custom.period == "custom-2026-05-01_to_2026-07-31"
    assert custom.label == "2026-05-01 to 2026-07-31"


def test_run_watchlist_can_replace_existing_raw_for_priority_order(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    import stratum.sourcing.watchlist as watchlist

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([
        {"url": "https://search.example.com/old", "title": "old search"}
    ]))

    class FakeResult:
        def to_dict(self):
            return {
                "url": "https://rss.example.com/new",
                "title": "new rss",
                "source_type_hint": "official",
                "locale": "en",
            }

    class FakeRun:
        results = [FakeResult()]
        source_stats = []

        def stats_json(self, domain, run_date):
            return {"domain": domain, "date": run_date, "sources": []}

    monkeypatch.setattr(watchlist, "collect_with_stats", lambda *args, **kwargs: FakeRun())

    status = pipeline._run_watchlist(
        "storage",
        str(tmp_path),
        "2026-05-30",
        str(raw_path),
        merge_existing=False,
    )

    raw = json.loads(raw_path.read_text())
    assert status["status"] == "success"
    assert [item["url"] for item in raw] == ["https://rss.example.com/new"]


def test_db_ingest_modes_follow_fresh_artifacts():
    from stratum.orchestrator.pipeline import db_ingest_modes

    assert db_ingest_modes(None) == {"events": True, "entities": True}
    assert db_ingest_modes("normalize") == {"events": True, "entities": True}
    assert db_ingest_modes("edit") == {"events": True, "entities": False}
    assert db_ingest_modes("validate") == {"events": False, "entities": False}
    assert db_ingest_modes("render") == {"events": False, "entities": False}
    assert db_ingest_modes(None, skip_agent=True) == {"events": False, "entities": True}


def test_expanded_source_locales_uses_config_expansions():
    from stratum.orchestrator.pipeline import expanded_source_locales

    assert expanded_source_locales({
        "source_languages": ["zh", "en", "zh-CN"],
        "locales": {"zh": ["zh-CN", "zh-TW"]},
    }) == ["zh-CN", "zh-TW", "en"]


def test_persist_event_watch_queries_uses_event_thread_generator(tmp_path):
    from stratum.orchestrator.pipeline import _persist_event_watch_queries

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [
            {
                "thread_id": "et-storage-0001",
                "title": "Samsung HBM4 qualification",
                "status": "cooling",
                "priority": "high",
                "watch_signals": ["Samsung HBM4 qualification"],
            },
            {
                "thread_id": "et-storage-0002",
                "title": "Resolved story",
                "status": "resolved",
                "priority": "high",
                "watch_signals": ["should not persist"],
            },
        ]
    }))
    captured = {}

    def fake_upsert(domain, watch_queries, run_date=None):
        captured["domain"] = domain
        captured["run_date"] = run_date
        captured["watch_queries"] = watch_queries
        return len(watch_queries)

    count = _persist_event_watch_queries(
        "storage",
        str(event_threads),
        ["en", "zh-CN"],
        fake_upsert,
        "2026-05-30",
    )

    assert count == 2
    assert captured["domain"] == "storage"
    assert captured["run_date"] == "2026-05-30"
    assert [q["locale"] for q in captured["watch_queries"]] == ["en", "zh-CN"]
    assert all(q["source"] == "thread:et-storage-0001" for q in captured["watch_queries"])


def test_persist_event_watch_queries_falls_back_to_thread_title(tmp_path):
    from stratum.orchestrator.pipeline import _persist_event_watch_queries

    event_threads = tmp_path / "event-threads.json"
    event_threads.write_text(json.dumps({
        "threads": [
            {
                "thread_id": "et-storage-0001",
                "title": "Samsung HBM4 qualification",
                "status": "active",
                "priority": "high",
                "watch_signals": [],
            }
        ]
    }))
    captured = {}

    def fake_upsert(domain, watch_queries, run_date=None):
        captured["watch_queries"] = watch_queries
        return len(watch_queries)

    count = _persist_event_watch_queries(
        "storage",
        str(event_threads),
        ["en"],
        fake_upsert,
        "2026-05-30",
    )

    assert count == 1
    assert captured["watch_queries"][0]["query"] == "Samsung HBM4 qualification"
    assert captured["watch_queries"][0]["source"] == "thread:et-storage-0001"


def test_thread_keywords_export_requires_fresh_successful_event_ingest():
    from stratum.orchestrator.pipeline import should_export_thread_keywords_after_ingest

    assert should_export_thread_keywords_after_ingest(
        {"events": True, "entities": True},
        {"status": "success"},
    )
    assert not should_export_thread_keywords_after_ingest(
        {"events": True, "entities": True},
        {"status": "failed_nonblocking"},
    )
    assert not should_export_thread_keywords_after_ingest(
        {"events": False, "entities": True},
        {"status": "success"},
    )


def test_try_db_ingest_reports_event_errors_nonblocking(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline

    db_path = tmp_path / "db" / "storage" / "storage.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("")
    data_dir = tmp_path / "run"
    data_dir.mkdir()
    (data_dir / "event-threads.json").write_text(json.dumps({"threads": []}))

    def fake_ingest_daily_events(path, domain, run_date):
        return {
            "events": 1,
            "causal_edges": 0,
            "judgments": 0,
            "new_threads": 1,
            "errors": ["FOREIGN KEY constraint failed"],
        }

    monkeypatch.setattr("stratum.db.ingest.ingest_daily_events", fake_ingest_daily_events)
    monkeypatch.setattr("stratum.db.ingest.update_entities_after_run", lambda *args, **kwargs: 0)
    monkeypatch.setattr("stratum.db.ingest.ingest_entity_snapshots", lambda *args, **kwargs: 0)
    monkeypatch.setattr("stratum.db.ingest.upsert_watch_queries", lambda *args, **kwargs: 0)

    status = pipeline._try_db_ingest(
        "storage",
        "2026-05-30",
        {"data_dir": str(data_dir), "articles": str(data_dir / "articles.jsonl")},
        str(tmp_path / "db"),
        ingest_events=True,
        ingest_entities=False,
    )

    assert status["status"] == "failed_nonblocking"
    assert "errors=1" in status["detail"]


def test_coverage_entities_load_from_domain_config(tmp_path):
    from stratum.orchestrator.pipeline import _coverage_entities_from_domain_config

    domain_config = tmp_path / "domain.yaml"
    domain_config.write_text("""
companies:
  - id: samsung
    aliases: {en: Samsung}
  - id: micron
    aliases: {en: Micron}
  - id: samsung
    aliases: {en: Samsung duplicate}
  - aliases: {en: Missing ID}
""")

    assert _coverage_entities_from_domain_config(str(domain_config)) == [
        "samsung",
        "micron",
    ]


def test_story_context_uses_domain_coverage_entities_on_empty_db(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.db import connection

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
            id TEXT,
            thread_id TEXT,
            title TEXT,
            date TEXT,
            entity_ids TEXT,
            scale TEXT,
            briefing_id TEXT,
            status TEXT,
            priority INTEGER
        );
        CREATE TABLE causal_edges (
            id TEXT,
            cause_thread_id TEXT,
            effect_thread_id TEXT,
            mechanism TEXT,
            confidence TEXT,
            verified INTEGER,
            created_at TEXT
        );
        CREATE TABLE judgments (
            id TEXT,
            target_type TEXT,
            target_entity_ids TEXT,
            target_thread_ids TEXT,
            hypothesis TEXT,
            confidence TEXT,
            expected_verification TEXT,
            result TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()

    def fake_get_db(domain):
        assert domain == "storage"
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr(connection, "get_db", fake_get_db)

    domain_config = tmp_path / "domain.yaml"
    domain_config.write_text("""
companies:
  - id: samsung
  - id: micron
""")
    output_path = tmp_path / "story_context.json"

    pipeline._try_generate_story_context(
        "storage",
        "2026-06-02",
        {"domain_config": str(domain_config)},
        str(output_path),
    )

    data = json.loads(output_path.read_text())
    assert [gap["entity"] for gap in data["coverage_gaps"]] == ["samsung", "micron"]
    assert all(gap["status"] == "never_seen" for gap in data["coverage_gaps"])


def test_write_run_manifest_records_stage_status(tmp_path):
    from stratum.orchestrator.pipeline import record_stage_status, write_run_manifest

    stages = []
    record_stage_status(stages, "search", "success", "/tmp/raw.json", "queries.yaml", {"duration_seconds": 1.25})
    record_stage_status(stages, "watchlist", "empty", "/tmp/watchlist_stats.json")

    manifest_path = tmp_path / "run_manifest.json"
    payload = write_run_manifest(
        str(manifest_path),
        "storage",
        "2026-05-30",
        "ok",
        stages,
        {"raw": "/tmp/raw.json", "run_manifest": str(manifest_path)},
        {"articles": 3, "clusters": 2},
    )

    on_disk = json.loads(manifest_path.read_text())
    assert payload == on_disk
    assert on_disk["status"] == "ok"
    assert on_disk["domain"] == "storage"
    assert on_disk["summary"] == {"articles": 3, "clusters": 2}
    assert on_disk["runtime"]["mode"] == "development"
    assert "commit" in on_disk["runtime"]
    assert on_disk["stages"][0]["stage"] == "search"
    assert on_disk["stages"][0]["status"] == "success"
    assert on_disk["stages"][0]["metrics"]["duration_seconds"] == 1.25
    assert on_disk["stages"][1]["status"] == "empty"


def test_write_run_manifest_accepts_locked_deployment_runtime(tmp_path):
    from stratum.orchestrator.pipeline import write_run_manifest

    manifest_path = tmp_path / "run_manifest.json"
    runtime = {
        "mode": "deployment",
        "version": "v0.1.1",
        "commit": "abc123",
        "git_tag": "v0.1.1",
        "locked": True,
        "deployment_id": "production-v0.1.1-abc123",
        "deployment_env": "production",
        "deployment_manifest": "/deploy/production/deployment_manifest.json",
    }

    payload = write_run_manifest(
        str(manifest_path),
        "storage",
        "2026-05-30",
        "ok",
        [],
        {"run_manifest": str(manifest_path)},
        runtime=runtime,
    )

    assert payload["runtime"] == runtime
    assert json.loads(manifest_path.read_text())["runtime"]["locked"] is True


def test_runtime_identity_uses_deployment_environment():
    from stratum.deployment import runtime_identity

    identity = runtime_identity({
        "STRATUM_RUNTIME_MODE": "deployment",
        "STRATUM_RELEASE_VERSION": "v0.1.1",
        "STRATUM_RELEASE_TAG": "v0.1.1",
        "STRATUM_RELEASE_COMMIT": "abc123",
        "STRATUM_DEPLOYMENT_ID": "production-v0.1.1-abc123",
        "STRATUM_DEPLOYMENT_ENV": "production",
        "STRATUM_DEPLOYMENT_MANIFEST": "/deploy/production/deployment_manifest.json",
    })

    assert identity["mode"] == "deployment"
    assert identity["version"] == "v0.1.1"
    assert identity["commit"] == "abc123"
    assert identity["locked"] is True


def test_run_watchlist_writes_stats_and_health(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.sourcing.watchlist import WatchlistRun, WatchlistSourceStats
    from stratum.sourcing.discovery import SearchResult
    import stratum.sourcing.watchlist as watchlist_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([{
        "url": "https://search.example.com/story",
        "title": "Search result",
    }]))

    watchlist_result = SearchResult(
        url="https://official.example.com/story",
        title="Official result",
        snippet="",
        locale="en",
        published_at="2026-05-30",
        source_domain="official.example.com",
        source_type_hint="official",
        engine="direct_fetch:official-source",
        query_id="official-source",
    )
    watchlist_run = WatchlistRun(
        results=[watchlist_result],
        source_stats=[
            WatchlistSourceStats(
                source="official-source",
                access="direct_fetch",
                status="ok",
                hits=1,
                duration_ms=12.3,
                locale="en",
                category="official",
                dated=1,
            )
        ],
    )

    health_dir = tmp_path / "health"
    channel_dir = health_dir / "storage"
    channel_dir.mkdir(parents=True)
    (channel_dir / "source-daily.ndjson").write_text(json.dumps({
        "date": "2026-05-29",
        "source": "official-source",
        "scanned": True,
        "hits": 2,
        "selected": 2,
        "http_code": 200,
        "tags": ["watchlist", "direct_fetch", "ok"],
    }) + "\n")
    captured = {}

    def fake_collect_with_stats(domain, workspace, run_date, **kwargs):
        captured["source_health"] = kwargs.get("source_health")
        return watchlist_run

    monkeypatch.setattr(watchlist_module, "collect_with_stats", fake_collect_with_stats)

    status = pipeline._run_watchlist("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    assert status["status"] == "success"
    assert status["output"] == str(tmp_path / "watchlist_stats.json")

    merged = json.loads(raw_path.read_text())
    assert [r["url"] for r in merged] == [
        "https://official.example.com/story",
        "https://search.example.com/story",
    ]
    watchlist_results = json.loads((tmp_path / "watchlist_results.json").read_text())
    assert [r["url"] for r in watchlist_results] == ["https://official.example.com/story"]
    assert watchlist_results[0]["canonical_url"] == "https://official.example.com/story"
    assert (tmp_path / "watchlist_observations.jsonl").read_text() == ""
    candidate_lines = (tmp_path / "watchlist_candidates.jsonl").read_text().splitlines()
    assert candidate_lines == []
    stats = json.loads((tmp_path / "watchlist_stats.json").read_text())
    assert stats["total_results"] == 1
    assert stats["sources"][0]["source"] == "official-source"
    assert stats["sources"][0]["status"] == "ok"
    assert stats["sources"][0]["selected"] == 1

    health_lines = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()
    health_record = json.loads(health_lines[-1])
    assert health_record["source"] == "official-source"
    assert health_record["hits"] == 1
    assert health_record["selected"] == 1
    assert health_record["metadata"]["dated"] == 1
    assert captured["source_health"]["official-source"]["selected_rate"] == 2.0


def test_run_watchlist_merge_dedupes_canonical_urls(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.sourcing.watchlist import WatchlistRun, WatchlistSourceStats
    from stratum.sourcing.discovery import SearchResult
    import stratum.sourcing.watchlist as watchlist_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([{
        "url": "https://m.example.com/story/?utm_source=search",
        "title": "Search duplicate",
    }]))

    watchlist_result = SearchResult(
        url="https://www.example.com/story",
        title="Collector canonical",
        snippet="",
        locale="en",
        published_at="2026-05-30",
        source_domain="example.com",
        source_type_hint="official",
        engine="direct_fetch:source",
        query_id="source",
    )
    watchlist_run = WatchlistRun(
        results=[watchlist_result],
        source_stats=[
            WatchlistSourceStats(source="source", access="direct_fetch", status="ok", hits=1, duration_ms=1.0)
        ],
    )

    monkeypatch.setattr(watchlist_module, "collect_with_stats", lambda domain, workspace, run_date, **kwargs: watchlist_run)

    health_dir = tmp_path / "health"
    pipeline._run_watchlist("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    merged = json.loads(raw_path.read_text())
    assert len(merged) == 1
    assert merged[0]["url"] == "https://www.example.com/story"
    assert merged[0]["canonical_url"] == "https://example.com/story"

    stats = json.loads((tmp_path / "watchlist_stats.json").read_text())
    assert stats["sources"][0]["hits"] == 1
    assert stats["sources"][0]["selected"] == 1


def test_run_watchlist_selected_counts_drop_duplicate_watchlist_results(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.sourcing.watchlist import WatchlistRun, WatchlistSourceStats
    from stratum.sourcing.discovery import SearchResult
    import stratum.sourcing.watchlist as watchlist_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]")

    watchlist_run = WatchlistRun(
        results=[
            SearchResult(
                url="https://www.example.com/story?utm_source=a",
                title="Collector A",
                snippet="",
                locale="en",
                source_domain="example.com",
                source_type_hint="official",
                engine="direct_fetch:source",
                query_id="source",
            ),
            SearchResult(
                url="https://m.example.com/story/",
                title="Collector duplicate",
                snippet="",
                locale="en",
                source_domain="example.com",
                source_type_hint="official",
                engine="direct_fetch:source",
                query_id="source",
            ),
        ],
        source_stats=[
            WatchlistSourceStats(source="source", access="direct_fetch", status="ok", hits=2, duration_ms=1.0)
        ],
    )

    monkeypatch.setattr(watchlist_module, "collect_with_stats", lambda domain, workspace, run_date, **kwargs: watchlist_run)

    health_dir = tmp_path / "health"
    pipeline._run_watchlist("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    stats = json.loads((tmp_path / "watchlist_stats.json").read_text())
    health_line = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()[0]
    health_record = json.loads(health_line)

    assert stats["sources"][0]["hits"] == 2
    assert stats["sources"][0]["selected"] == 1
    assert health_record["hits"] == 2
    assert health_record["selected"] == 1


def test_run_watchlist_selected_counts_use_engine_source_id_not_query_id(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.sourcing.watchlist import WatchlistRun, WatchlistSourceStats
    from stratum.sourcing.discovery import SearchResult
    import stratum.sourcing.watchlist as watchlist_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]")

    watchlist_run = WatchlistRun(
        results=[
            SearchResult(
                url="https://example.com/story",
                title="RSS result",
                snippet="",
                locale="en",
                source_domain="example.com",
                source_type_hint="media",
                engine="rss:storagenewsletter-rss",
                query_id="rss-storagenewsletter-rss",
            )
        ],
        source_stats=[
            WatchlistSourceStats(
                source="storagenewsletter-rss",
                access="rss",
                status="ok",
                hits=1,
                duration_ms=1.0,
            )
        ],
    )

    monkeypatch.setattr(watchlist_module, "collect_with_stats", lambda domain, workspace, run_date, **kwargs: watchlist_run)

    health_dir = tmp_path / "health"
    pipeline._run_watchlist("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    stats = json.loads((tmp_path / "watchlist_stats.json").read_text())
    health_line = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()[0]
    health_record = json.loads(health_line)

    assert stats["sources"][0]["selected"] == 1
    assert health_record["selected"] == 1


def test_run_watchlist_health_marks_unsupported_sources_unscanned(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.sourcing.watchlist import WatchlistRun, WatchlistSourceStats
    import stratum.sourcing.watchlist as watchlist_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]")

    watchlist_run = WatchlistRun(
        results=[],
        source_stats=[
            WatchlistSourceStats(
                source="browser-source",
                access="browser",
                status="unsupported",
                hits=0,
                duration_ms=1.0,
                error="Playwright is not installed",
            )
        ],
    )

    monkeypatch.setattr(watchlist_module, "collect_with_stats", lambda domain, workspace, run_date, **kwargs: watchlist_run)

    health_dir = tmp_path / "health"
    pipeline._run_watchlist("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    health_line = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()[0]
    health_record = json.loads(health_line)

    assert json.loads((tmp_path / "watchlist_results.json").read_text()) == []
    assert (tmp_path / "watchlist_observations.jsonl").read_text() == ""
    assert (tmp_path / "watchlist_candidates.jsonl").read_text() == ""
    assert health_record["source"] == "browser-source"
    assert health_record["scanned"] is False
    assert health_record["metadata"]["status"] == "unsupported"
    assert health_record["tags"] == ["watchlist", "browser", "unsupported"]


def test_update_post_collect_search_stats_adds_final_coverage(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline

    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]")
    stats_path = tmp_path / "raw.stats.json"
    stats_path.write_text(json.dumps({"diagnostics": {}}))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
curation:
  min_per_source_type:
    official: 2
    media: 1
""")
    monkeypatch.setattr(pipeline, "CONFIG_PATH", str(config_path))

    pipeline._update_post_collect_search_stats(str(raw_path), [
        {"source_type_hint": "official", "locale": "en"},
        {"source_type_hint": "official", "locale": "en"},
        {"source_type_hint": "media", "locale": "zh-CN"},
    ])

    diagnostics = json.loads(stats_path.read_text())["diagnostics"]
    assert diagnostics["post_collect_total_raw"] == 3
    assert diagnostics["post_collect_by_source_type"] == {"official": 2, "media": 1}
    assert diagnostics["post_collect_source_type_gaps"] == []


def test_remove_legacy_briefing_artifacts_keeps_canonical(tmp_path):
    from stratum.orchestrator.pipeline import _remove_legacy_briefing_artifacts

    for name in ("briefing.md", "briefing.html", "briefing.pdf"):
        (tmp_path / name).write_text("old")
    canonical_md = tmp_path / "Storage_Daily_Briefing_2026-05-30.md"
    canonical_html = tmp_path / "Storage_Daily_Briefing_2026-05-30.html"
    canonical_pdf = tmp_path / "Storage_Daily_Briefing_2026-05-30.pdf"
    for path in (canonical_md, canonical_html, canonical_pdf):
        path.write_text("new")

    _remove_legacy_briefing_artifacts({
        "data_dir": str(tmp_path),
        "briefing_md": str(canonical_md),
        "briefing_html": str(canonical_html),
        "briefing_pdf": str(canonical_pdf),
    })

    assert not (tmp_path / "briefing.md").exists()
    assert not (tmp_path / "briefing.html").exists()
    assert not (tmp_path / "briefing.pdf").exists()
    assert canonical_md.exists()
    assert canonical_html.exists()
    assert canonical_pdf.exists()


def test_clear_delivery_artifacts_removes_canonical_outputs(tmp_path):
    from stratum.orchestrator.artifacts import clear_delivery_artifacts

    paths = {
        "briefing_md": str(tmp_path / "Storage_Daily_Briefing_2026-05-30.md"),
        "briefing_html": str(tmp_path / "Storage_Daily_Briefing_2026-05-30.html"),
        "briefing_pdf": str(tmp_path / "Storage_Daily_Briefing_2026-05-30.pdf"),
        "raw": str(tmp_path / "raw.json"),
    }
    for key, path in paths.items():
        Path(path).write_text(key)

    clear_delivery_artifacts(paths)

    assert not Path(paths["briefing_md"]).exists()
    assert not Path(paths["briefing_html"]).exists()
    assert not Path(paths["briefing_pdf"]).exists()
    assert Path(paths["raw"]).exists()


def test_daily_evidence_window_can_express_48_hours():
    from argparse import Namespace
    from stratum.orchestrator.pipeline import _append_daily_acquisition_window, _daily_evidence_window

    args = Namespace(
        timescale="daily",
        date="2026-05-31",
        start_date=None,
        end_date=None,
        lookback_hours=48,
    )

    window = _daily_evidence_window(args)
    search_args = _append_daily_acquisition_window(["--domain", "storage"], window)

    assert window == {
        "start_date": "2026-05-30",
        "end_date": "2026-05-31",
        "stale_days": 2,
        "window_days": 2,
        "lookback_hours": 48,
    }
    assert search_args[-4:] == ["--start-date", "2026-05-30", "--end-date", "2026-05-31"]


def test_daily_evidence_window_derives_custom_range_days():
    from argparse import Namespace
    from stratum.orchestrator.pipeline import _daily_evidence_window

    args = Namespace(
        timescale="daily",
        date="2026-05-31",
        start_date="2026-05-29",
        end_date="2026-05-31",
        lookback_hours=None,
    )

    assert _daily_evidence_window(args) == {
        "start_date": "2026-05-29",
        "end_date": "2026-05-31",
        "stale_days": 3,
        "window_days": 3,
        "lookback_hours": None,
    }


def test_remove_legacy_raw_artifacts_keeps_single_canonical_raw(tmp_path):
    from stratum.orchestrator.pipeline import _remove_legacy_raw_artifacts

    raw_path = tmp_path / "raw.json"
    stats_path = tmp_path / "raw.stats.json"
    legacy_collector_stats = tmp_path / "collector_stats.json"
    raw_path.write_text("[]")
    stats_path.write_text("{}")
    legacy_collector_stats.write_text("{}")
    for name in (
        "raw.full.json",
        "raw_full.json",
        "raw.curated.json",
        "raw.search.json",
        "search_raw.json",
        "watchlist_raw.json",
    ):
        (tmp_path / name).write_text("[]")

    _remove_legacy_raw_artifacts({
        "data_dir": str(tmp_path),
        "raw": str(raw_path),
    })

    assert raw_path.exists()
    assert stats_path.exists()
    assert not legacy_collector_stats.exists()
    assert not any(
        (tmp_path / name).exists()
        for name in (
            "raw.full.json",
            "raw_full.json",
            "raw.curated.json",
            "raw.search.json",
            "search_raw.json",
            "watchlist_raw.json",
        )
    )


def test_search_stage_status_marks_failed_nonblocking_when_discovery_fails(tmp_path):
    from stratum.orchestrator.pipeline import _search_stage_status

    stats_path = tmp_path / "raw.stats.json"
    stats_path.write_text(json.dumps({
        "total_raw": 12,
        "diagnostics": {"search_raw": 0},
        "queries": [
            {"query_id": "q-1", "status": "failed"},
            {"query_id": "q-2", "status": "failed"},
            {"query_id": "q-3", "status": "skipped_covered"},
        ],
    }))

    assert _search_stage_status(str(stats_path)) == (
        "failed_nonblocking",
        "all discovery queries failed",
    )


def test_search_stage_status_keeps_success_when_watchlist_only_merge_has_results(tmp_path):
    from stratum.orchestrator.pipeline import _search_stage_status

    stats_path = tmp_path / "raw.stats.json"
    stats_path.write_text(json.dumps({
        "total_raw": 12,
        "diagnostics": {"search_raw": 0},
        "queries": [
            {"query_id": "q-1", "status": "no_results"},
            {"query_id": "q-2", "status": "failed"},
        ],
    }))

    assert _search_stage_status(str(stats_path)) == ("success", None)


def test_try_ingest_search_stats_reads_sidecar(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    import stratum.db.ingest as ingest

    stats_path = tmp_path / "raw.stats.json"
    stats_path.write_text(json.dumps({
        "diagnostics": {
            "engine_health": {
                "tavily": {"engine": "tavily", "attempts": 1, "successes": 1}
            }
        },
        "queries": [
            {"query_id": "q-1", "results_count": 4, "locale": "en", "intent": "detection"},
            {"query_id": "q-2", "results_count": 0, "locale": "zh-CN", "intent": "verification"},
        ]
    }))

    captured = {}

    def fake_update_query_stats(domain, query_stats, run_date=None, engine_health=None):
        captured["domain"] = domain
        captured["query_stats"] = query_stats
        captured["run_date"] = run_date
        captured["engine_health"] = engine_health
        return len(query_stats)

    monkeypatch.setattr(ingest, "update_query_stats", fake_update_query_stats)

    count = pipeline._try_ingest_search_stats("storage", str(stats_path), "2026-05-30")

    assert count == 2
    assert captured["domain"] == "storage"
    assert captured["run_date"] == "2026-05-30"
    assert captured["query_stats"][0]["query_id"] == "q-1"
    assert captured["engine_health"]["tavily"]["attempts"] == 1


def test_try_db_ingest_can_skip_entity_counts_for_edit_resume(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline

    db_path = tmp_path / "db" / "storage" / "storage.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("")
    data_dir = tmp_path / "run"
    data_dir.mkdir()
    (data_dir / "articles.jsonl").write_text(json.dumps({
        "id": "a1",
        "entities": ["Samsung"],
    }) + "\n")

    calls = {"events": 0, "entities": 0, "snapshots": 0}

    def fake_ingest_daily_events(path, domain, run_date):
        calls["events"] += 1
        return {"events": 0, "causal_edges": 0, "judgments": 0, "new_threads": 0, "errors": []}

    def fake_update_entities_after_run(domain, stats, run_date=None):
        calls["entities"] += 1
        return len(stats)

    def fake_ingest_entity_snapshots(domain, scale, period, entity_article_counts=None):
        calls["snapshots"] += 1
        return 1

    monkeypatch.setattr("stratum.db.ingest.ingest_daily_events", fake_ingest_daily_events)
    monkeypatch.setattr("stratum.db.ingest.update_entities_after_run", fake_update_entities_after_run)
    monkeypatch.setattr("stratum.db.ingest.ingest_entity_snapshots", fake_ingest_entity_snapshots)

    status = pipeline._try_db_ingest(
        "storage",
        "2026-05-30",
        {"data_dir": str(data_dir), "articles": str(data_dir / "articles.jsonl")},
        str(tmp_path / "db"),
        ingest_events=True,
        ingest_entities=False,
    )

    assert status["status"] == "success"
    assert calls == {"events": 0, "entities": 0, "snapshots": 0}
    assert "entities=off" in status["detail"]


def test_try_db_ingest_uses_pipeline_db_dir(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.db import connection

    db_dir = tmp_path / "pipeline-db"
    db_path = db_dir / "storage" / "storage.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("")

    data_dir = tmp_path / "run"
    data_dir.mkdir()

    seen = {}

    def fake_ingest_entity_snapshots(domain, scale, period, entity_article_counts=None):
        seen["db_path"] = connection.get_db_path(domain)
        return 0

    monkeypatch.delenv("STRATUM_DB_DIR", raising=False)
    monkeypatch.setattr("stratum.db.ingest.ingest_entity_snapshots", fake_ingest_entity_snapshots)
    monkeypatch.setattr("stratum.db.ingest.update_entities_after_run", lambda domain, stats, run_date=None: 0)

    status = pipeline._try_db_ingest(
        "storage",
        "2026-05-30",
        {"data_dir": str(data_dir), "articles": str(data_dir / "articles.jsonl")},
        str(db_dir),
        ingest_events=False,
        ingest_entities=True,
    )

    assert status["status"] == "success"
    assert seen["db_path"] == str(db_path)


def test_try_db_ingest_persists_foundation_report_bundle(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.db.connection import get_db
    from stratum.db.migration import apply_foundation_migration

    db_dir = tmp_path / "db"
    monkeypatch.setenv("STRATUM_DB_DIR", str(db_dir))
    conn = get_db("storage")
    apply_foundation_migration(conn)
    conn.close()

    data_dir = tmp_path / "run"
    data_dir.mkdir()
    paths = {
        "data_dir": str(data_dir),
        "articles": str(data_dir / "articles.jsonl"),
        "briefing_plan": str(data_dir / "briefing_plan.json"),
        "briefing_chunks": str(data_dir / "briefing_chunks.json"),
        "briefing_md": str(data_dir / "Storage_Daily_Briefing_2026-05-30.md"),
        "briefing_html": str(data_dir / "Storage_Daily_Briefing_2026-05-30.html"),
        "briefing_pdf": str(data_dir / "Storage_Daily_Briefing_2026-05-30.pdf"),
        "raw": str(data_dir / "raw.json"),
        "validate_report": str(data_dir / "validate_report.json"),
        "repair_report": str(data_dir / "repair_report.json"),
        "run_manifest": str(data_dir / "run_manifest.json"),
    }
    (data_dir / "articles.jsonl").write_text(json.dumps({
        "id": "a1",
        "title": "Samsung HBM4 qualification",
        "url": "https://example.com/a1",
        "source": "Example",
        "published_at": "2026-05-30",
        "snippet": "Samsung HBM4 qualification advances.",
        "entities": ["samsung"],
        "terms": ["hbm"],
    }) + "\n")
    (data_dir / "event-threads.json").write_text(json.dumps({
        "threads": [{
            "thread_id": "et-storage-0001",
            "title": "Samsung HBM4 qualification",
            "priority": "high",
            "article_ids": ["a1"],
            "entity_ids": ["samsung"],
            "term_ids": ["hbm"],
        }],
        "causal_edges": [],
        "judgments": [],
    }))
    (data_dir / "briefing_plan.json").write_text(json.dumps({
        "items": [{
            "item_id": "item-main-1",
            "kind": "main",
            "sequence": 1,
            "title_hint": "Samsung HBM4 qualification",
            "thread_id": "et-storage-0001",
            "article_ids": ["a1"],
        }],
    }))
    (data_dir / "briefing_chunks.json").write_text(json.dumps([{
        "block_index": 1,
        "category_id": "cat-1",
        "label": "HBM",
        "items": [{
            "item_id": "item-main-1",
            "title": "Samsung HBM4 qualification",
            "paragraphs": ["Samsung advances HBM4 qualification."],
        }],
    }]))
    (data_dir / "validate_report.json").write_text(json.dumps({"status": "ok", "items": 1, "violations": 0, "summary": {"invalid_items": 0}, "details": []}))
    (data_dir / "repair_report.json").write_text(json.dumps({"status": "no_changes", "input_status": "ok", "input_violations": 0, "validate_rounds": 1, "rewritten_items": 0, "dropped_items": 0, "unchanged_invalid_items": 0, "item_actions": []}))
    for key in ("briefing_md", "briefing_html", "briefing_pdf", "raw", "run_manifest"):
        (data_dir / paths[key].split("/")[-1]).write_text(key)

    status = pipeline._try_db_ingest(
        "storage",
        "2026-05-30",
        paths,
        str(db_dir),
        ingest_events=True,
        ingest_entities=False,
    )

    conn = get_db("storage")
    try:
        report = conn.execute("SELECT * FROM reports WHERE id = 'report-storage-daily-2026-05-30'").fetchone()
        item = conn.execute("SELECT * FROM report_items WHERE id LIKE 'report-storage-daily-2026-05-30-%'").fetchone()
        evidence = conn.execute("SELECT * FROM report_item_articles WHERE article_id = 'a1'").fetchone()
        event_link = conn.execute("SELECT * FROM event_articles WHERE article_id = 'a1'").fetchone()
        manifest_artifact = conn.execute(
            "SELECT * FROM report_artifacts WHERE artifact_type = 'run_manifest'"
        ).fetchone()
        validate_artifact = conn.execute(
            "SELECT * FROM report_artifacts WHERE artifact_type = 'validate_report'"
        ).fetchone()
        repair_artifact = conn.execute(
            "SELECT * FROM report_artifacts WHERE artifact_type = 'repair_report'"
        ).fetchone()
    finally:
        conn.close()

    assert status["status"] == "success"
    assert "foundation=success" in status["detail"]
    assert report["markdown_path"] == paths["briefing_md"]
    assert item["title"] == "Samsung HBM4 qualification"
    assert evidence["report_item_id"] == item["id"]
    assert event_link["event_id"] == "ev-2026-05-30-et-storage-0001"
    assert manifest_artifact["path"] == paths["run_manifest"]
    assert validate_artifact["path"] == paths["validate_report"]
    assert repair_artifact["path"] == paths["repair_report"]


def test_pipeline_main_repair_branch_runs_validate_repair_recheck_and_render(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline

    config_path = tmp_path / "config.yaml"
    reports_dir = tmp_path / "Reports"
    db_dir = tmp_path / "DB"
    health_dir = tmp_path / "health"
    config_path.write_text(
        "\n".join([
            f'output_dir: "{tmp_path}"',
            f'reports_dir: "{reports_dir}"',
            f'db_dir: "{db_dir}"',
            f'health_data_dir: "{health_dir}"',
        ])
    )

    data_dir = reports_dir / "storage" / "data" / "2026-06-01"
    data_dir.mkdir(parents=True)
    (data_dir / "articles.jsonl").write_text(json.dumps({
        "id": "a1",
        "title": "Samsung reportedly raises prices",
        "source": "trendforce.com",
        "published_at": "2026-06-01",
        "snippet": "TrendForce reported memory price moves.",
    }) + "\n")
    (data_dir / "clusters.json").write_text(json.dumps({"clusters": []}))
    (data_dir / "event-threads.json").write_text(json.dumps({"threads": [], "causal_edges": [], "judgments": []}))
    briefing_path = data_dir / "Storage_Daily_Briefing_2026-06-01.md"
    briefing_path.write_text(
        "# 存储早报\n\n## 2026年6月1日 · 周一\n\n### Samsung reportedly raises prices\n\n消息称价格已经确认上行。\n\n*trendforce.com · 2026年6月1日*\n"
    )

    stage_calls = []

    def fake_run_stage(stage_name, stage_args, step_label, timeout=120):
        stage_calls.append(stage_name)
        if stage_name == "validate":
            output = Path(stage_args[stage_args.index("--output-report") + 1])
            output.write_text(json.dumps({
                "status": "violations",
                "items": 1,
                "violations": 1,
                "summary": {
                    "item_violations": 1,
                    "boilerplate_violations": 0,
                    "structured_output_violations": 0,
                    "invalid_items": 1,
                },
                "details": [{
                    "item": 1,
                    "kind": "item",
                    "title": "Samsung reportedly raises prices",
                    "sources": ["trendforce.com"],
                    "date": "2026年6月1日",
                    "violations": ["OVERCLAIM: reported_signal_overstated_as_confirmed"],
                }],
            }))
            return False
        if stage_name == "repair":
            md_path = Path(stage_args[stage_args.index("--md") + 1])
            md_path.write_text(
                "# 存储早报\n\n## 2026年6月1日 · 周一\n\n### [News] Samsung, SK hynix Reportedly Lift Memory Prices Up to 30%; Long-Term Supply Deals in Play\n\nTrendForce reported pricing moves.\n\n*trendforce.com · 2026年6月1日*\n"
            )
            output = Path(stage_args[stage_args.index("--output-report") + 1])
            output.write_text(json.dumps({
                "status": "repaired",
                "input_status": "violations",
                "input_violations": 1,
                "validate_rounds": 2,
                "rewritten_items": 1,
                "dropped_items": 0,
                "unchanged_invalid_items": 0,
                "item_actions": [{
                    "item": 1,
                    "section": "行业要点",
                    "title": "Samsung reportedly raises prices",
                    "action": "rewrite",
                    "reason": "rewrite_title_and_body_from_support_article",
                    "violations": ["OVERCLAIM: reported_signal_overstated_as_confirmed"],
                    "support_article_id": "a1",
                    "support_source": "trendforce.com",
                }],
            }))
            return True
        if stage_name == "validate_recheck":
            output = Path(stage_args[stage_args.index("--output-report") + 1])
            output.write_text(json.dumps({
                "status": "ok",
                "items": 1,
                "violations": 0,
                "summary": {
                    "item_violations": 0,
                    "boilerplate_violations": 0,
                    "structured_output_violations": 0,
                    "invalid_items": 0,
                },
                "details": [],
            }))
            return True
        if stage_name == "render":
            output_dir = Path(stage_args[stage_args.index("--output-dir") + 1])
            artifact_md = Path(stage_args[stage_args.index("--input") + 1])
            artifact_base = artifact_md.stem
            (output_dir / f"{artifact_base}.html").write_text("<html></html>")
            (output_dir / f"{artifact_base}.pdf").write_text("pdf")
            return True
        return True

    monkeypatch.setattr(pipeline, "run_stage", fake_run_stage)
    monkeypatch.setattr(sys, "argv", [
        "pipeline.py",
        "--domain", "storage",
        "--date", "2026-06-01",
        "--config", str(config_path),
        "--from-stage", "validate",
    ])

    pipeline.main()

    manifest = json.loads((data_dir / "run_manifest.json").read_text())
    repair_report = json.loads((data_dir / "repair_report.json").read_text())

    assert stage_calls == ["validate", "repair", "validate_recheck", "render"]
    assert manifest["status"] == "ok"
    assert [stage["stage"] for stage in manifest["stages"] if stage["status"] != "skipped"][-4:] == [
        "validate", "repair", "validate_recheck", "render"
    ]
    assert manifest["stages"][7]["status"] == "violations"
    assert manifest["stages"][8]["status"] == "success"
    assert manifest["stages"][9]["status"] == "success"
    assert manifest["summary"]["quality"]["validate_status"] == "ok"
    assert manifest["summary"]["quality"]["rewritten_items"] == 1
    assert repair_report["rewritten_items"] == 1


def test_higher_scale_output_writes_markdown_render_and_manifest(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.db.connection import get_db
    from stratum.db.migration import apply_foundation_migration
    from stratum.temporal.timescale import TemporalServices, run_higher_scale_output

    paths = pipeline.resolve_paths("storage", "2026-W22", str(tmp_path), "weekly")
    paths["domain_config"] = str(tmp_path / "domains" / "storage" / "domain.yaml")
    paths["config"] = str(tmp_path / "config.yaml")
    paths["output_dir"] = str(tmp_path)
    paths["reports_dir"] = str(tmp_path)
    paths["db_dir"] = str(tmp_path / "db")
    paths["health_data_dir"] = str(tmp_path / "health")
    paths["enriched"] = str(tmp_path / "enriched.json")
    monkeypatch.setenv("STRATUM_DB_DIR", paths["db_dir"])
    conn = get_db("storage")
    apply_foundation_migration(conn)
    conn.close()
    template_dir = tmp_path / "storage" / "templates"
    template_dir.mkdir(parents=True)
    (tmp_path / "domains" / "storage").mkdir(parents=True)
    (tmp_path / "domains" / "storage" / "domain.yaml").write_text("domain:\n  title: 存储早报\n")
    (tmp_path / "domains" / "storage" / "queries.yaml").write_text("queries: {}\n")
    (template_dir / "weekly.html").write_text("<html><body>{title}{date_str}{body}{footer}</body></html>")
    stages = []

    def record(stage, status, output=None, detail=None):
        pipeline.record_stage_status(stages, stage, status, output, detail)

    def fail(stage, output=None, detail=None):
        raise AssertionError(f"unexpected failure {stage}: {detail}")

    def fake_synthesize(domain, scale, period, **kwargs):
        return {
            "report_id": "report-storage-weekly-2026-W22",
            "source_scale": "daily",
            "source_scales": ["daily"],
            "source_reports": 2,
            "source_events": 3,
            "fresh_evidence": 0,
            "synthesized_events": 1,
        }

    def fake_context(domain, scale, period, **kwargs):
        return {
            "report": {"id": "report-storage-weekly-2026-W22"},
            "sections": [{"id": "sec-1", "title": "本周综合", "position": 1}],
            "items": [{
                "id": "item-1",
                "section_id": "sec-1",
                "title": "HBM weekly synthesis",
                "body": "HBM continued as the dominant thread.",
                "signal_type": "trend",
            }],
        }

    def fake_run_stage(stage_name, stage_args, step_label, timeout=120):
        (tmp_path / "stage_label.txt").write_text(step_label)
        recorded_args = json.loads((tmp_path / "stage_args.json").read_text()) if (tmp_path / "stage_args.json").exists() else []
        recorded_args.append([stage_name, stage_args])
        (tmp_path / "stage_args.json").write_text(json.dumps(recorded_args))
        if stage_name == "acquisition":
            raw_path = stage_args[stage_args.index("--output") + 1]
            os.makedirs(os.path.dirname(raw_path), exist_ok=True)
            with open(raw_path, "w") as f:
                json.dump([], f)
            stats_path = stage_args[stage_args.index("--stats") + 1]
            with open(stats_path, "w") as f:
                json.dump({"queries": []}, f)
        elif stage_name == "enrich":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                json.dump([], f)
        elif stage_name == "verify":
            output = stage_args[stage_args.index("--output") + 1]
            open(output, "w").close()
            with open(stage_args[stage_args.index("--stats") + 1], "w") as f:
                json.dump({"total": 0, "verified": 0}, f)
        elif stage_name == "normalize":
            open(stage_args[stage_args.index("--output") + 1], "w").close()
        elif stage_name == "render":
            output_dir = stage_args[stage_args.index("--output-dir") + 1]
            artifact_name = stage_args[stage_args.index("--artifact-name") + 1]
            os.makedirs(output_dir, exist_ok=True)
            (tmp_path / "storage" / "data" / "weekly" / "2026-W22" / f"{artifact_name}.html").write_text("<html></html>")
            (tmp_path / "storage" / "data" / "weekly" / "2026-W22" / f"{artifact_name}.pdf").write_text("pdf")
        return True

    monkeypatch.setattr("stratum.db.synthesis.synthesize_cascade_report", fake_synthesize)
    monkeypatch.setattr("stratum.db.service.get_report_context", fake_context)
    result = run_higher_scale_output(
        "storage",
        "weekly",
        "2026-W22",
        paths,
        {"mode": "development"},
        stages,
        record,
        fail,
        TemporalServices(
            run_stage=fake_run_stage,
            write_manifest=pipeline.write_run_manifest,
            domains_dir=str(tmp_path),
        ),
    )

    md = (tmp_path / "storage" / "data" / "weekly" / "2026-W22" / "Storage_Weekly_Briefing_2026-W22.md").read_text()
    manifest = json.loads((tmp_path / "storage" / "data" / "weekly" / "2026-W22" / "run_manifest.json").read_text())
    stage_calls = json.loads((tmp_path / "stage_args.json").read_text())
    render_args = [args for stage, args in stage_calls if stage == "render"][0]
    search_args = [args for stage, args in stage_calls if stage == "acquisition"][0]

    assert result["status"] == "ok"
    assert result["timescale"] == "weekly"
    assert md.startswith("# 存储周报\n\n## 2026-W22（2026-05-25 至 2026-05-31）")
    assert "### HBM weekly synthesis" in md
    assert "HBM continued as the dominant thread." in md
    assert manifest["summary"]["report_id"] == "report-storage-weekly-2026-W22"
    assert [stage["stage"] for stage in manifest["stages"]] == ["exploring", "db_synthesis", "markdown", "render"]
    assert "--start-date" in search_args
    assert search_args[search_args.index("--start-date") + 1] == "2026-05-25"
    assert search_args[search_args.index("--end-date") + 1] == "2026-05-31"
    assert "--briefing-type" in render_args
    assert render_args[render_args.index("--briefing-type") + 1] == "weekly"
    assert render_args[render_args.index("--artifact-name") + 1] == "Storage_Weekly_Briefing_2026-W22"
    assert render_args[render_args.index("--title") + 1] == "存储周报"
    assert render_args[render_args.index("--date") + 1] == "2026-W22（2026-05-25 至 2026-05-31）"
    assert render_args[render_args.index("--template") + 1].endswith("templates/weekly.html")
    assert manifest["summary"]["profile"]["stage_order"] == ["exploring", "db_synthesis", "markdown", "render"]
    assert manifest["summary"]["profile"]["consumes_lower_scales"] is True
    assert manifest["summary"]["profile"]["consumes_same_scale_fresh_evidence"] is True
    assert manifest["summary"]["profile"]["synthesis_policy_profile"] == "weekly"
    assert manifest["summary"]["exploring"]["status"] == "success"
    assert manifest["summary"]["integration"]["role"] == "db_memory_only_no_fresh_hits"
    assert manifest["summary"]["integration"]["use_db_memory"] is True
    assert manifest["summary"]["integration"]["include_same_scale_fresh"] is False


def test_higher_scale_output_supports_custom_window(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.temporal.timescale import TemporalServices, run_higher_scale_output

    period = "custom-2026-05-01_to_2026-07-31"
    paths = pipeline.resolve_paths("storage", period, str(tmp_path), "monthly")
    paths["domain_config"] = str(tmp_path / "domains" / "storage" / "domain.yaml")
    paths["config"] = str(tmp_path / "config.yaml")
    os.makedirs(os.path.dirname(paths["domain_config"]), exist_ok=True)
    with open(paths["domain_config"], "w") as f:
        f.write("domain:\n  title: 存储早报\n")
    stages = []

    def record(stage, status, output=None, detail=None):
        pipeline.record_stage_status(stages, stage, status, output, detail)

    def fail(stage, output=None, detail=None):
        raise AssertionError(f"unexpected failure {stage}: {detail}")

    def fake_synthesize(domain, scale, target_period, **kwargs):
        assert target_period == period
        assert kwargs["window_start"] == "2026-05-01"
        assert kwargs["window_end"] == "2026-07-31"
        return {
            "report_id": f"report-storage-monthly-{period}",
            "source_scale": "weekly",
            "source_scales": ["daily", "weekly"],
            "source_reports": 4,
            "source_events": 9,
            "fresh_evidence": 2,
            "synthesized_events": 3,
        }

    def fake_context(domain, scale, target_period, **kwargs):
        assert kwargs["window_start"] == "2026-05-01"
        return {
            "report": {"id": f"report-storage-monthly-{period}"},
            "sections": [],
            "items": [],
        }

    def fake_run_stage(stage_name, stage_args, step_label, timeout=120):
        (tmp_path / "stage_args.json").write_text(json.dumps(stage_args))
        return True

    monkeypatch.setattr("stratum.db.synthesis.synthesize_cascade_report", fake_synthesize)
    monkeypatch.setattr("stratum.db.service.get_report_context", fake_context)

    result = run_higher_scale_output(
        "storage",
        "monthly",
        period,
        paths,
        {"mode": "development"},
        stages,
        record,
        fail,
        TemporalServices(
            run_stage=fake_run_stage,
            write_manifest=pipeline.write_run_manifest,
            domains_dir=str(tmp_path),
        ),
        window_start="2026-05-01",
        window_end="2026-07-31",
    )

    stage_args = json.loads((tmp_path / "stage_args.json").read_text())
    assert result["summary"]["window"]["period_kind"] == "custom_range"
    assert result["summary"]["period"] == period
    assert stage_args[stage_args.index("--date") + 1] == "2026-05-01 to 2026-07-31"


def test_exploring_persists_weekly_articles(tmp_path, monkeypatch):
    from stratum.contracts.report_window import resolve_report_window
    from stratum.db.connection import get_db
    from stratum.db.migration import apply_foundation_migration
    from stratum.temporal.exploring import run_exploring
    from stratum.temporal.timescale import TemporalServices

    db_dir = tmp_path / "db"
    monkeypatch.setenv("STRATUM_DB_DIR", str(db_dir))
    conn = get_db("storage")
    apply_foundation_migration(conn)
    conn.close()

    domain_root = tmp_path / "domains" / "storage"
    domain_root.mkdir(parents=True)
    (domain_root / "queries.yaml").write_text("queries: {}\n")
    (domain_root / "domain.yaml").write_text("domain:\n  title: 存储早报\n")
    data_dir = tmp_path / "reports" / "storage" / "data" / "weekly" / "2026-W22"
    data_dir.mkdir(parents=True)
    paths = {
        "raw": str(data_dir / "raw.json"),
        "search_stats": str(data_dir / "raw.stats.json"),
        "enriched": str(data_dir / "enriched.json"),
        "verified": str(data_dir / "verified.jsonl"),
        "verify_stats": str(data_dir / "verified.stats.json"),
        "articles": str(data_dir / "articles.jsonl"),
        "domain_config": str(domain_root / "domain.yaml"),
    }

    def fake_run_stage(stage_name, stage_args, step_label, timeout=120):
        if stage_name == "acquisition":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                json.dump([], f)
            with open(stage_args[stage_args.index("--stats") + 1], "w") as f:
                json.dump({"queries": []}, f)
        elif stage_name == "enrich":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                json.dump([], f)
        elif stage_name == "verify":
            open(stage_args[stage_args.index("--output") + 1], "w").close()
            with open(stage_args[stage_args.index("--stats") + 1], "w") as f:
                json.dump({"total": 0, "verified": 0}, f)
        elif stage_name == "normalize":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                f.write(json.dumps({
                    "id": "weekly-fresh-1",
                    "title": "Weekly HBM customer validation",
                    "url": "https://example.com/weekly-hbm",
                    "source": "Example",
                    "published_at": "2026-05-31",
                    "entity_ids": ["samsung"],
                    "term_ids": ["hbm"],
                }) + "\n")
        return True

    stages = []
    result = run_exploring(
        "storage",
        "weekly",
        "2026-W22",
        resolve_report_window("weekly", "2026-W22"),
        paths,
        str(tmp_path / "config.yaml"),
        str(db_dir),
        TemporalServices(
            run_stage=fake_run_stage,
            write_manifest=lambda *args, **kwargs: {},
            domains_dir=str(tmp_path / "domains"),
        ),
        lambda stage, status, output=None, detail=None: stages.append({
            "stage": stage,
            "status": status,
            "detail": detail,
        }),
    )

    conn = get_db("storage")
    try:
        row = conn.execute("SELECT scale, run_date, title FROM articles WHERE id = 'weekly-fresh-1'").fetchone()
    finally:
        conn.close()

    assert result["status"] == "success"
    assert result["articles"] == 1
    assert result["integration_point"] == "after_normalize_db_persist_before_db_synthesis"
    assert result["integration"]["role"] == "fresh_only_watch"
    assert result["integration"]["include_same_scale_fresh"] is True
    assert stages[-1]["stage"] == "exploring"
    assert row["scale"] == "weekly"
    assert row["run_date"] == "2026-W22"
    assert row["title"] == "Weekly HBM customer validation"


def test_temporal_exploring_and_integration_are_separate():
    from stratum.contracts.report_window import resolve_report_window
    from stratum.temporal.exploring import Exploring
    from stratum.temporal.integration import Integration

    exploring = Exploring()
    integration = Integration(exploring)

    assert exploring.enabled_for("daily") is False
    for scale in ("weekly", "monthly", "quarterly", "yearly"):
        assert exploring.enabled_for(scale) is True
        assert integration.include_same_scale_fresh(scale, {"status": "success", "articles": 1}) is True
        assert integration.include_same_scale_fresh(scale, {"status": "success", "articles": 0}) is False
        assert integration.include_same_scale_fresh(scale, {"status": "failed_nonblocking", "articles": 3}) is False
    exploring_plan = exploring.plan("weekly", resolve_report_window("weekly", "2026-W22"))
    assert exploring_plan.should_explore is True
    assert exploring_plan.stale_days == 7
    decision = integration.decide(
        "weekly",
        {"status": "success", "articles": 2},
        db_memory={"source_reports": 1, "source_events": 3},
    )
    assert decision.role == "fresh_supplements_db_memory"
    assert decision.use_db_memory is True
    assert decision.include_same_scale_fresh is True


def test_exploring_persists_monthly_articles(tmp_path, monkeypatch):
    from stratum.contracts.report_window import resolve_report_window
    from stratum.db.connection import get_db
    from stratum.db.migration import apply_foundation_migration
    from stratum.temporal.exploring import run_exploring
    from stratum.temporal.timescale import TemporalServices

    db_dir = tmp_path / "db"
    monkeypatch.setenv("STRATUM_DB_DIR", str(db_dir))
    conn = get_db("storage")
    apply_foundation_migration(conn)
    conn.close()

    domain_root = tmp_path / "domains" / "storage"
    domain_root.mkdir(parents=True)
    (domain_root / "queries.yaml").write_text("queries: {}\n")
    (domain_root / "domain.yaml").write_text("domain:\n  title: 存储早报\n")
    data_dir = tmp_path / "reports" / "storage" / "data" / "monthly" / "2026-05"
    data_dir.mkdir(parents=True)
    paths = {
        "raw": str(data_dir / "raw.json"),
        "search_stats": str(data_dir / "raw.stats.json"),
        "enriched": str(data_dir / "enriched.json"),
        "verified": str(data_dir / "verified.jsonl"),
        "verify_stats": str(data_dir / "verified.stats.json"),
        "articles": str(data_dir / "articles.jsonl"),
        "domain_config": str(domain_root / "domain.yaml"),
    }
    seen_verify_args = []

    def fake_run_stage(stage_name, stage_args, step_label, timeout=120):
        del step_label, timeout
        if stage_name == "acquisition":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                json.dump([], f)
            with open(stage_args[stage_args.index("--stats") + 1], "w") as f:
                json.dump({"queries": []}, f)
        elif stage_name == "enrich":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                json.dump([], f)
        elif stage_name == "verify":
            seen_verify_args.extend(stage_args)
            open(stage_args[stage_args.index("--output") + 1], "w").close()
            with open(stage_args[stage_args.index("--stats") + 1], "w") as f:
                json.dump({"total": 0, "verified": 0}, f)
        elif stage_name == "normalize":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                f.write(json.dumps({
                    "id": "monthly-fresh-1",
                    "title": "Monthly HBM validation",
                    "url": "https://example.com/monthly-hbm",
                    "source": "Example",
                    "published_at": "2026-05-31",
                    "entity_ids": ["samsung"],
                    "term_ids": ["hbm"],
                }) + "\n")
        return True

    result = run_exploring(
        "storage",
        "monthly",
        "2026-05",
        resolve_report_window("monthly", "2026-05"),
        paths,
        str(tmp_path / "config.yaml"),
        str(db_dir),
        TemporalServices(
            run_stage=fake_run_stage,
            write_manifest=lambda *args, **kwargs: {},
            domains_dir=str(tmp_path / "domains"),
        ),
        lambda *args, **kwargs: None,
    )

    conn = get_db("storage")
    try:
        row = conn.execute("SELECT scale, run_date, title FROM articles WHERE id = 'monthly-fresh-1'").fetchone()
    finally:
        conn.close()

    assert result["status"] == "success"
    assert result["articles"] == 1
    assert seen_verify_args[seen_verify_args.index("--stale-days") + 1] == "31"
    assert row["scale"] == "monthly"
    assert row["run_date"] == "2026-05"


def test_exploring_marks_all_search_failures_nonblocking(tmp_path):
    from stratum.contracts.report_window import resolve_report_window
    from stratum.temporal.exploring import run_exploring
    from stratum.temporal.timescale import TemporalServices

    domain_root = tmp_path / "domains" / "storage"
    domain_root.mkdir(parents=True)
    (domain_root / "queries.yaml").write_text("queries: {}\n")
    (domain_root / "domain.yaml").write_text("domain:\n  title: 存储早报\n")
    data_dir = tmp_path / "reports" / "storage" / "data" / "weekly" / "2026-W22"
    data_dir.mkdir(parents=True)
    paths = {
        "raw": str(data_dir / "raw.json"),
        "search_stats": str(data_dir / "raw.stats.json"),
        "enriched": str(data_dir / "enriched.json"),
        "verified": str(data_dir / "verified.jsonl"),
        "verify_stats": str(data_dir / "verified.stats.json"),
        "articles": str(data_dir / "articles.jsonl"),
        "domain_config": str(domain_root / "domain.yaml"),
    }
    called_stages = []

    def fake_run_stage(stage_name, stage_args, step_label, timeout=120):
        del step_label, timeout
        called_stages.append(stage_name)
        if stage_name == "acquisition":
            with open(stage_args[stage_args.index("--output") + 1], "w") as f:
                json.dump([], f)
            with open(stage_args[stage_args.index("--stats") + 1], "w") as f:
                json.dump({
                    "total_raw": 0,
                    "queries": [
                        {"query_id": "q1", "status": "failed"},
                        {"query_id": "q2", "status": "failed"},
                    ],
                }, f)
        return True

    stages = []
    result = run_exploring(
        "storage",
        "weekly",
        "2026-W22",
        resolve_report_window("weekly", "2026-W22"),
        paths,
        str(tmp_path / "config.yaml"),
        str(tmp_path / "db"),
        TemporalServices(
            run_stage=fake_run_stage,
            write_manifest=lambda *args, **kwargs: {},
            domains_dir=str(tmp_path / "domains"),
        ),
        lambda stage, status, output=None, detail=None: stages.append({
            "stage": stage,
            "status": status,
            "detail": detail,
        }),
    )

    assert result["status"] == "failed_nonblocking"
    assert result["articles"] == 0
    assert result["integration_point"] == "not_reached"
    assert result["integration"]["role"] == "insufficient_evidence"
    assert called_stages == ["acquisition"]
    assert stages[-1]["status"] == "failed_nonblocking"
    assert stages[-1]["detail"] == "all search queries failed"


def test_timescale_profiles_keep_shared_and_specific_contracts():
    from stratum.temporal.profiles import get_timescale_profile

    daily = get_timescale_profile("daily")
    weekly = get_timescale_profile("weekly")
    yearly = get_timescale_profile("yearly")

    assert daily.uses_daily_pipeline is True
    assert daily.stage_order == (
        "acquisition",
        "enrich",
        "verify",
        "normalize",
        "cluster",
        "edit",
        "validate",
        "repair",
        "validate_recheck",
        "render",
    )
    assert weekly.uses_daily_pipeline is False
    assert weekly.stage_order == ("exploring", "db_synthesis", "markdown", "render")
    assert weekly.synthesis_policy_profile == "weekly"
    assert yearly.template_name == "yearly.html"
    assert yearly.consumes_lower_scales is True
    assert yearly.consumes_same_scale_fresh_evidence is True
    assert yearly.synthesis_policy_profile == "yearly"
