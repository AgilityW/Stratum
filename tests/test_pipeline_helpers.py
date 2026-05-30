"""Regression tests for orchestrator helper behavior."""

import json
import sqlite3
import pytest


def test_export_thread_keywords_has_regex_available(tmp_path, monkeypatch):
    """Exporting thread keywords should write tokens instead of swallowing NameError."""
    from stratum.orchestrator import pipeline
    from stratum.db import connection

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

    monkeypatch.setattr(connection, "get_db", fake_get_db)
    out_path = tmp_path / "thread_keywords.json"

    pipeline._export_thread_keywords("storage", {"thread_keywords": str(out_path)})

    data = json.loads(out_path.read_text())
    assert data["threads"][0]["thread_id"] == "et-storage-0001"
    assert "samsung" in data["threads"][0]["keywords"]


def test_export_thread_keywords_aggregates_events_by_thread(tmp_path, monkeypatch):
    """One continuing story should export one keyword profile, not one per event."""
    from stratum.orchestrator import pipeline
    from stratum.db import connection

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

    monkeypatch.setattr(connection, "get_db", fake_get_db)
    out_path = tmp_path / "thread_keywords.json"

    pipeline._export_thread_keywords("storage", {"thread_keywords": str(out_path)})

    data = json.loads(out_path.read_text())
    assert len(data["threads"]) == 1
    thread = data["threads"][0]
    assert thread["thread_id"] == "et-storage-0001"
    assert thread["status"] == "active"
    assert {"samsung", "sk-hynix", "hbm4"}.issubset(set(thread["keywords"]))


def test_browser_collector_reports_missing_playwright(monkeypatch):
    from stratum.collectors import browser

    monkeypatch.setattr(browser, "find_spec", lambda name: None)

    try:
        browser.ensure_browser_available()
    except browser.BrowserCollectorUnavailable as exc:
        assert "pip install -e '.[browser]'" in str(exc)
    else:
        raise AssertionError("expected BrowserCollectorUnavailable")


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


def test_run_collector_can_replace_existing_raw_for_priority_order(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    import stratum.collectors as collectors

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

    monkeypatch.setattr(collectors, "collect_with_stats", lambda *args: FakeRun())

    status = pipeline._run_collector(
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
    record_stage_status(stages, "search", "success", "/tmp/raw.json", "queries.yaml")
    record_stage_status(stages, "collectors", "empty", "/tmp/collector_stats.json")

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
    assert on_disk["stages"][0]["stage"] == "search"
    assert on_disk["stages"][0]["status"] == "success"
    assert on_disk["stages"][1]["status"] == "empty"


def test_run_collector_writes_stats_and_health(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.collectors import CollectorRun, CollectorSourceStats
    from stratum.subsystems.search.models import SearchResult
    import stratum.collectors as collectors_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([{
        "url": "https://search.example.com/story",
        "title": "Search result",
    }]))

    collector_result = SearchResult(
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
    collector_run = CollectorRun(
        results=[collector_result],
        source_stats=[
            CollectorSourceStats(
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

    monkeypatch.setattr(collectors_module, "collect_with_stats", lambda domain, workspace, run_date: collector_run)

    health_dir = tmp_path / "health"
    status = pipeline._run_collector("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    assert status["status"] == "success"
    assert status["output"] == str(tmp_path / "collector_stats.json")

    merged = json.loads(raw_path.read_text())
    assert [r["url"] for r in merged] == [
        "https://official.example.com/story",
        "https://search.example.com/story",
    ]

    stats = json.loads((tmp_path / "collector_stats.json").read_text())
    assert stats["total_results"] == 1
    assert stats["sources"][0]["source"] == "official-source"
    assert stats["sources"][0]["status"] == "ok"
    assert stats["sources"][0]["selected"] == 1

    health_lines = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()
    health_record = json.loads(health_lines[0])
    assert health_record["source"] == "official-source"
    assert health_record["hits"] == 1
    assert health_record["selected"] == 1
    assert health_record["metadata"]["dated"] == 1


def test_run_collector_merge_dedupes_canonical_urls(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.collectors import CollectorRun, CollectorSourceStats
    from stratum.subsystems.search.models import SearchResult
    import stratum.collectors as collectors_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([{
        "url": "https://m.example.com/story/?utm_source=search",
        "title": "Search duplicate",
    }]))

    collector_result = SearchResult(
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
    collector_run = CollectorRun(
        results=[collector_result],
        source_stats=[
            CollectorSourceStats(source="source", access="direct_fetch", status="ok", hits=1, duration_ms=1.0)
        ],
    )

    monkeypatch.setattr(collectors_module, "collect_with_stats", lambda domain, workspace, run_date: collector_run)

    health_dir = tmp_path / "health"
    pipeline._run_collector("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    merged = json.loads(raw_path.read_text())
    assert len(merged) == 1
    assert merged[0]["url"] == "https://www.example.com/story"
    assert merged[0]["canonical_url"] == "https://example.com/story"

    stats = json.loads((tmp_path / "collector_stats.json").read_text())
    assert stats["sources"][0]["hits"] == 1
    assert stats["sources"][0]["selected"] == 1


def test_run_collector_selected_counts_drop_duplicate_collector_results(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.collectors import CollectorRun, CollectorSourceStats
    from stratum.subsystems.search.models import SearchResult
    import stratum.collectors as collectors_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]")

    collector_run = CollectorRun(
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
            CollectorSourceStats(source="source", access="direct_fetch", status="ok", hits=2, duration_ms=1.0)
        ],
    )

    monkeypatch.setattr(collectors_module, "collect_with_stats", lambda domain, workspace, run_date: collector_run)

    health_dir = tmp_path / "health"
    pipeline._run_collector("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    stats = json.loads((tmp_path / "collector_stats.json").read_text())
    health_line = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()[0]
    health_record = json.loads(health_line)

    assert stats["sources"][0]["hits"] == 2
    assert stats["sources"][0]["selected"] == 1
    assert health_record["hits"] == 2
    assert health_record["selected"] == 1


def test_run_collector_selected_counts_use_engine_source_id_not_query_id(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.collectors import CollectorRun, CollectorSourceStats
    from stratum.subsystems.search.models import SearchResult
    import stratum.collectors as collectors_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]")

    collector_run = CollectorRun(
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
            CollectorSourceStats(
                source="storagenewsletter-rss",
                access="rss",
                status="ok",
                hits=1,
                duration_ms=1.0,
            )
        ],
    )

    monkeypatch.setattr(collectors_module, "collect_with_stats", lambda domain, workspace, run_date: collector_run)

    health_dir = tmp_path / "health"
    pipeline._run_collector("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    stats = json.loads((tmp_path / "collector_stats.json").read_text())
    health_line = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()[0]
    health_record = json.loads(health_line)

    assert stats["sources"][0]["selected"] == 1
    assert health_record["selected"] == 1


def test_run_collector_health_marks_unsupported_sources_unscanned(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    from stratum.collectors import CollectorRun, CollectorSourceStats
    import stratum.collectors as collectors_module

    raw_path = tmp_path / "raw.json"
    raw_path.write_text("[]")

    collector_run = CollectorRun(
        results=[],
        source_stats=[
            CollectorSourceStats(
                source="browser-source",
                access="browser",
                status="unsupported",
                hits=0,
                duration_ms=1.0,
                error="Playwright is not installed",
            )
        ],
    )

    monkeypatch.setattr(collectors_module, "collect_with_stats", lambda domain, workspace, run_date: collector_run)

    health_dir = tmp_path / "health"
    pipeline._run_collector("storage", str(tmp_path), "2026-05-30", str(raw_path), str(health_dir))

    health_line = (health_dir / "storage" / "source-daily.ndjson").read_text().splitlines()[0]
    health_record = json.loads(health_line)

    assert health_record["source"] == "browser-source"
    assert health_record["scanned"] is False
    assert health_record["metadata"]["status"] == "unsupported"
    assert health_record["tags"] == ["collector", "browser", "unsupported"]


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


def test_remove_legacy_raw_artifacts_keeps_single_canonical_raw(tmp_path):
    from stratum.orchestrator.pipeline import _remove_legacy_raw_artifacts

    raw_path = tmp_path / "raw.json"
    stats_path = tmp_path / "raw.stats.json"
    raw_path.write_text("[]")
    stats_path.write_text("{}")
    for name in (
        "raw.full.json",
        "raw_full.json",
        "raw.curated.json",
        "raw.search.json",
        "search_raw.json",
        "collector_raw.json",
    ):
        (tmp_path / name).write_text("[]")

    _remove_legacy_raw_artifacts({
        "data_dir": str(tmp_path),
        "raw": str(raw_path),
    })

    assert raw_path.exists()
    assert stats_path.exists()
    assert not any(
        (tmp_path / name).exists()
        for name in (
            "raw.full.json",
            "raw_full.json",
            "raw.curated.json",
            "raw.search.json",
            "search_raw.json",
            "collector_raw.json",
        )
    )


def test_try_ingest_search_stats_reads_sidecar(tmp_path, monkeypatch):
    from stratum.orchestrator import pipeline
    import stratum.db.ingest as ingest

    stats_path = tmp_path / "raw.stats.json"
    stats_path.write_text(json.dumps({
        "queries": [
            {"query_id": "q-1", "results_count": 4, "locale": "en", "intent": "detection"},
            {"query_id": "q-2", "results_count": 0, "locale": "zh-CN", "intent": "verification"},
        ]
    }))

    captured = {}

    def fake_update_query_stats(domain, query_stats, run_date=None):
        captured["domain"] = domain
        captured["query_stats"] = query_stats
        captured["run_date"] = run_date
        return len(query_stats)

    monkeypatch.setattr(ingest, "update_query_stats", fake_update_query_stats)

    count = pipeline._try_ingest_search_stats("storage", str(stats_path), "2026-05-30")

    assert count == 2
    assert captured["domain"] == "storage"
    assert captured["run_date"] == "2026-05-30"
    assert captured["query_stats"][0]["query_id"] == "q-1"


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
