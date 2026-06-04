"""Contract schema smoke tests against current stage output shapes."""

import json
from pathlib import Path

from jsonschema import Draft7Validator, validate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = PROJECT_ROOT / "stratum" / "contracts"


def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text())


def test_contract_schemas_parse():
    for path in CONTRACTS.glob("*.json"):
        data = json.loads(path.read_text())
        assert data.get("type") == "object", path.name
        Draft7Validator.check_schema(data)


def test_raw_search_result_schema_accepts_search_and_watchlist_shapes():
    schema = _schema("search_result.json")

    validate({
        "url": "https://example.com/story",
        "title": "Samsung HBM4 update",
        "snippet": "HBM4 production update",
        "description": "HBM4 production update",
        "datePublished": "2026-05-30",
        "locale": "en",
        "published_at": "2026-05-30",
        "source_domain": "example.com",
        "source_type_hint": "media",
        "engine": "tavily",
        "query_id": "q-1",
        "query_used": "q-1",
        "query_dimension": "verification",
        "score": 0.81,
        "canonical_url": "https://example.com/story",
        "date_source": "search_api",
    }, schema)

    validate({
        "url": "https://micron.com/news/story",
        "title": "Micron memory update",
        "snippet": "",
        "engine": "direct_fetch:micron-newsroom",
        "source_domain": "micron.com",
        "source_type_hint": "official",
        "locale": "en",
        "date_source": "url_path",
    }, schema)


def test_raw_search_stats_schema_accepts_search_stats_shape():
    schema = _schema("search_stats.json")

    validate({
        "date": "2026-05-30",
        "total_raw": 3,
        "total_curated": 2,
        "by_engine": {"tavily": 2},
        "by_locale": {"en": 2},
        "by_source_type": {"media": 2},
        "diagnostics": {
            "raw_by_locale": {"en": 3},
            "curated_by_locale": {"en": 2},
            "raw_by_source_type": {"media": 3},
            "curated_by_source_type": {"media": 2},
            "raw_by_dimension": {"technology": 3},
            "curated_by_dimension": {"technology": 2},
            "dimension_coverage": [
                {"dimension": "technology", "queries": 1, "raw": 3, "curated": 2}
            ],
            "locale_coverage": [
                {"locale": "en", "queries": 1, "raw": 3, "curated": 2}
            ],
            "source_type_gaps": [
                {
                    "source_type": "official",
                    "minimum": 1,
                    "raw_available": 0,
                    "curated": 0,
                    "shortfall": 1,
                }
            ],
            "domain_filter_coverage": [
                {
                    "include_domain": "example.com",
                    "queries": 1,
                    "failed_queries": 0,
                    "raw": 1,
                    "curated": 1,
                }
            ],
            "top_source_domains": [
                {"domain": "example.com", "raw": 2, "curated": 1}
            ],
            "low_yield_queries": [
                {
                    "query_id": "q-zh",
                    "engine_used": "bocha",
                    "status": "no_results",
                    "results_count": 0,
                    "locale": "zh-CN",
                    "intent": "detection",
                    "dimension": "technology",
                    "query_text": "HBM4",
                    "include_domains": ["example.com"],
                    "retries": 0,
                    "latency_ms": 12.4,
                    "error": None,
                }
            ],
        },
        "queries": [
            {
                "query_id": "q-en",
                "engine_used": "tavily",
                "status": "success",
                "results_count": 3,
                "locale": "en",
                "intent": "detection",
                "dimension": "technology",
                "query_text": "HBM4",
                "retries": 0,
                "latency_ms": 10.0,
                "error": None,
            }
        ],
    }, schema)


def test_watchlist_stats_schema_accepts_health_sidecar_shape():
    schema = _schema("watchlist_stats.json")

    validate({
        "domain": "storage",
        "date": "2026-05-30",
        "total_results": 3,
        "sources": [
            {
                "source": "micron-newsroom",
                "access": "direct_fetch",
                "status": "ok",
                "hits": 3,
                "selected": 2,
                "duration_ms": 12.5,
                "locale": "en",
                "category": "official",
                "dated": 2,
            },
            {
                "source": "custom-source",
                "access": "unknown",
                "status": "unsupported",
                "hits": 0,
                "selected": 0,
                "duration_ms": 0.2,
                "dated": 0,
                "error": "unknown access type: custom_api",
            },
        ],
    }, schema)


def test_verified_article_schema_accepts_date_lineage():
    schema = _schema("verified_article.json")

    validate({
        "id": "raw-0001",
        "url": "https://reuters.com/technology/story",
        "canonical_url": "https://reuters.com/technology/story",
        "title": "Memory prices rise",
        "source": "reuters.com",
        "snippet": "DRAM prices rise",
        "engine": "tavily",
        "date_source": "url_path",
        "verification_status": "verified",
        "rejection_reason": None,
        "published_at": "2026-05-30T00:00:00+08:00",
        "corroboration_score": 4.0,
        "corroboration_level": "high",
        "corroborating_sources": ["trendforce.com"],
        "raw_metadata": {"locale": "en"},
    }, schema)


def test_validate_report_schema_accepts_validate_sidecar_shape():
    schema = _schema("validate_report.json")

    validate({
        "status": "violations",
        "items": 2,
        "violations": 3,
        "summary": {
            "item_violations": 3,
            "boilerplate_violations": 0,
            "structured_output_violations": 0,
            "invalid_items": 2
        },
        "details": [{
            "item": 1,
            "kind": "item",
            "title": "Samsung reportedly raises prices",
            "sources": ["trendforce.com"],
            "date": "2026年6月1日",
            "violations": ["OVERCLAIM: reported_signal_overstated_as_confirmed"]
        }]
    }, schema)


def test_repair_report_schema_accepts_validate_repair_shape():
    schema = _schema("repair_report.json")

    validate({
        "status": "repaired",
        "input_status": "violations",
        "input_violations": 4,
        "validate_rounds": 2,
        "rewritten_items": 3,
        "dropped_items": 1,
        "unchanged_invalid_items": 0,
        "item_actions": [{
            "item": 3,
            "section": "行业要点",
            "title": "Samsung reportedly raises prices",
            "action": "rewrite",
            "reason": "rewrite_title_and_body_from_support_article",
            "violations": ["OVERCLAIM: reported_signal_overstated_as_confirmed"],
            "support_article_id": "a1",
            "support_source": "trendforce.com"
        }]
    }, schema)


def test_signal_awareness_schema_accepts_detection_payload():
    schema = _schema("signal_awareness.json")

    validate({
        "version": "0.1",
        "domain": "storage",
        "run_date": "2026-06-03",
        "snapshot": {
            "date": "2026-06-03",
            "total_records": 12,
            "topic_counts": {"memory": 6},
            "anchor_counts": {"computex_2026": 3}
        },
        "topic_signals": [{
            "topic_id": "memory",
            "current_count": 6,
            "baseline_mean": 2.0,
            "baseline_std": 1.0,
            "z_score": 4.0,
            "anomalous": True,
            "history_points": 7
        }],
        "anchor_signals": [{
            "anchor_id": "computex_2026",
            "anchor_name": "Computex 2026",
            "topics": ["memory"],
            "mention_count": 3,
            "source_count": 3,
            "company_diversity": 3,
            "official_hits": 1,
            "location_hits": 2,
            "event_clue_hits": 3,
            "year_hits": 3,
            "coherence_score": 0.7,
            "confidence": 0.8,
            "detected": True,
            "window_status": "lead_window",
            "representative_titles": ["Computex preview"],
            "temporary_sources": ["computex-rss"],
            "direct_fetch_targets": ["https://example.com/live"],
            "query_terms": ["computex 2026 storage"],
            "daily_target_min": 16,
            "daily_target_max": 24
        }],
        "unanchored_clusters": [{
            "cluster_key": "taipei-ssd",
            "label": "Taipei Ssd",
            "record_count": 2,
            "sources": ["feed-a", "feed-b"],
            "representative_titles": ["Taipei summit preview highlights SSD vendors"]
        }],
        "diagnostics": {
            "record_count": 12,
            "topic_rule_count": 1,
            "anchor_count": 1,
            "active_signal_count": 0,
            "anomalous_topics": 1,
            "detected_anchors": 1,
            "cluster_count": 1
        }
    }, schema)


def test_capability_invocation_schema_accepts_mcp_ready_shape():
    schema = _schema("capability_invocation.json")

    validate({
        "version": "0.1",
        "capability": "source_trace.run",
        "arguments": {
            "input_dir": "/tmp/run",
            "write_csv": False,
        },
    }, schema)


def test_capability_result_schema_accepts_success_and_error_shapes():
    schema = _schema("capability_result.json")

    validate({
        "version": "0.1",
        "capability": "signal_awareness.run",
        "status": "ok",
        "payload": {"domain": "storage"},
        "error": None,
    }, schema)

    validate({
        "version": "0.1",
        "capability": "signal_awareness.run",
        "status": "error",
        "payload": None,
        "error": {
            "type": "ValueError",
            "message": "bad input",
        },
    }, schema)


def test_agent_task_schema_accepts_agent_ready_shape():
    schema = _schema("agent_task.json")

    validate({
        "version": "0.1",
        "task": "analyze_signal_landscape",
        "arguments": {
            "domain": "storage",
            "data_dir": "/tmp/run",
        },
    }, schema)


def test_agent_task_result_schema_accepts_task_step_summary():
    schema = _schema("task_result.json")

    validate({
        "version": "0.1",
        "task": "analyze_signal_landscape",
        "status": "ok",
        "steps": [
            {"capability": "source_trace.run", "status": "ok"},
            {"capability": "signal_bursts.run", "status": "ok"},
        ],
        "result": {
            "source_trace": {"source_trace_summary": {"status": "ok"}},
        },
        "error": None,
    }, schema)


def test_signal_activation_plan_schema_accepts_planning_payload():
    schema = _schema("signal_plan.json")

    validate({
        "run_date": "2026-06-03",
        "default_daily_target": 8,
        "actions": [{
            "anchor_id": "computex_2026",
            "anchor_name": "Computex 2026",
            "action": "activate",
            "reason": "lead_window_or_confirmed_burst",
            "confidence": 0.8,
            "mention_count": 3,
            "max_topic_z_score": 4.2,
            "window_status": "lead_window",
            "decay_streak": 0,
            "daily_target_before": 8,
            "daily_target_after": {"min": 16, "max": 24},
            "temporary_sources": ["computex-rss"],
            "direct_fetch_targets": ["https://example.com/live"],
            "query_injections": ["computex 2026 storage"]
        }],
        "summary": {
            "activate": 1,
            "maintain": 0,
            "archive": 0,
            "observe": 0
        }
    }, schema)


def test_article_record_schema_accepts_normalize_output_shape():
    schema = _schema("article_record.json")

    validate({
        "id": "abc123",
        "url": "https://reuters.com/technology/story",
        "canonical_url": "https://reuters.com/technology/story",
        "title": "Memory prices rise",
        "source": "reuters.com",
        "source_type": "media",
        "source_locale": "en",
        "published_at": "2026-05-30T00:00:00+08:00",
        "date_source": "url_path",
        "fetched_at": "2026-05-30T08:00:00+08:00",
        "snippet": "DRAM prices rise",
        "extracted_summary": "DRAM prices rise",
        "content_hash": "hash",
        "entities": ["Samsung"],
        "entity_ids": ["samsung"],
        "terms": ["DRAM"],
        "term_ids": ["dram"],
        "numeric_claims": [],
        "typed_numeric_claims": [
            {
                "claim_type": "price_change",
                "text": "DRAM prices rise 15%",
                "value": 15,
                "unit": "percent",
                "direction": "up",
                "metric": "price",
            }
        ],
        "verification_status": "verified",
        "rejection_reason": None,
        "discovery_mode": "baseline_seed",
        "engine": "tavily",
        "query_id": "q-1",
        "query_used": "q-1",
        "query_dimension": "verification",
        "artifact_type": "news_article",
        "cluster_id": None,
        "event_thread_id": None,
    }, schema)


def test_article_record_schema_accepts_bcp47_locale_variants():
    schema = _schema("article_record.json")

    validate({
        "id": "abc124",
        "url": "https://example.com/technology/story",
        "canonical_url": "https://example.com/technology/story",
        "title": "Memory supply update",
        "source": "example.com",
        "source_type": "media",
        "source_locale": "zh-Hans-CN",
        "published_at": "2026-05-30T00:00:00+08:00",
        "date_source": "search_api",
        "fetched_at": "2026-05-30T08:00:00+08:00",
        "snippet": "Supply update",
        "extracted_summary": "Supply update",
        "content_hash": "hash",
        "entities": [],
        "terms": [],
        "numeric_claims": [],
        "verification_status": "verified",
        "rejection_reason": None,
        "discovery_mode": "baseline_seed",
        "query_dimension": "technology",
        "artifact_type": "news_article",
    }, schema)


def test_story_cluster_schema_accepts_cluster_output_shape():
    schema = _schema("story_cluster.json")

    validate({
        "id": "sc-storage-0001",
        "canonical_title": "Samsung HBM4 update",
        "canonical_summary": "Samsung HBM4 production update.",
        "confidence": "medium",
        "confidence_score": 0.62,
        "article_ids": ["a1", "a2"],
        "article_count": 2,
        "source_types": ["media", "official"],
        "locales": ["en"],
        "source_domains": ["reuters.com", "samsung.com"],
        "canonical_urls": [
            "https://reuters.com/technology/story",
            "https://samsung.com/news/story",
        ],
        "entities": ["Samsung"],
        "terms": ["HBM4"],
        "created": "2026-05-30",
    }, schema)


def test_story_cluster_schema_accepts_domain_ids_with_digits_and_hyphens():
    schema = _schema("story_cluster.json")

    validate({
        "id": "sc-ai-storage2-0001",
        "canonical_title": "AI storage demand update",
        "confidence": "low",
        "article_ids": ["a1", "a2"],
        "article_count": 2,
        "source_types": ["media"],
        "locales": ["en"],
        "source_domains": ["example.com"],
        "canonical_urls": ["https://example.com/a", "https://example.com/b"],
        "created": "2026-05-30",
    }, schema)
