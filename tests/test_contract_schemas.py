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


def test_raw_search_result_schema_accepts_search_and_collector_shapes():
    schema = _schema("raw_search_result.json")

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
    schema = _schema("raw_search_stats.json")

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


def test_collector_stats_schema_accepts_health_sidecar_shape():
    schema = _schema("collector_stats.json")

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
        "raw_metadata": {"locale": "en"},
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
        "terms": ["DRAM"],
        "numeric_claims": [],
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
