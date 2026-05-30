"""Runtime data integrity checks for current Stratum pipeline artifacts.

These tests inspect the latest local run under:
    {config.output_dir}/{domain}/data/{YYYY-MM-DD}/

If no local run exists, these tests generate a minimal golden run directory so
cross-artifact checks still execute in CI and fresh clones.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest
from jsonschema import validate


RUN_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _contract_schema(name: str) -> dict:
    return json.loads((PROJECT_ROOT / "stratum" / "contracts" / name).read_text())


def _output_root() -> Path:
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        cfg_path = os.path.join(current, "config.yaml")
        if os.path.exists(cfg_path):
            import yaml
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
            return Path(os.path.expanduser(cfg.get("output_dir", "~/WorkSpace/Stratum")))
        current = os.path.dirname(current)
    return Path(os.path.expanduser("~/WorkSpace/Stratum"))


def _find_latest_run_dir(domain: str = "storage") -> Path | None:
    base = _output_root() / domain / "data"
    if not base.exists():
        return None
    dirs = [
        d for d in base.iterdir()
        if d.is_dir() and RUN_DIR_RE.match(d.name)
    ]
    return sorted(dirs, key=lambda d: d.name, reverse=True)[0] if dirs else None


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                pytest.fail(f"{path.name} line {i}: invalid JSON - {e}")
    return rows


def _load_clusters(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    clusters = data.get("clusters", [])
    assert isinstance(clusters, list), "clusters must be a list"
    return clusters


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_golden_run_dir(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_results = [
        {
            "url": "https://news.skhynix.com/hbm4",
            "canonical_url": "https://news.skhynix.com/hbm4",
            "title": "SK hynix HBM4 Mass Production",
            "snippet": "Mass production of HBM4 begins.",
            "description": "Mass production of HBM4 begins.",
            "datePublished": "2026-05-30T09:00:00+08:00",
            "locale": "en",
            "published_at": "2026-05-30T09:00:00+08:00",
            "source_domain": "news.skhynix.com",
            "source_type_hint": "official",
            "engine": "direct_fetch:sk-hynix-newsroom",
            "query_id": "collector-sk-hynix-newsroom",
            "query_used": "collector source",
            "query_dimension": "official_sources",
            "score": 1.0,
            "date_source": "url_path",
        },
        {
            "url": "https://semiconductor-today.com/samsung-hbm4?utm_source=news",
            "canonical_url": "https://semiconductor-today.com/samsung-hbm4",
            "title": "Samsung ships HBM4 to NVIDIA",
            "snippet": "HBM4 samples shipped to NVIDIA.",
            "description": "HBM4 samples shipped to NVIDIA.",
            "datePublished": "2026-05-30T11:00:00+08:00",
            "locale": "en",
            "published_at": "2026-05-30T11:00:00+08:00",
            "source_domain": "semiconductor-today.com",
            "source_type_hint": "media",
            "engine": "tavily",
            "query_id": "q-storage-001",
            "query_used": "Samsung HBM4 NVIDIA",
            "query_dimension": "technology",
            "score": 0.81,
            "date_source": "search_api",
        },
    ]
    _write_json(run_dir / "raw.json", raw_results)
    _write_json(run_dir / "enriched.json", raw_results)

    verified_rows = [
        {
            "id": "raw-0001",
            "url": raw_results[0]["url"],
            "canonical_url": raw_results[0]["canonical_url"],
            "title": raw_results[0]["title"],
            "source": raw_results[0]["source_domain"],
            "snippet": raw_results[0]["snippet"],
            "query_used": raw_results[0]["query_used"],
            "engine": raw_results[0]["engine"],
            "date_source": raw_results[0]["date_source"],
            "verification_status": "verified",
            "rejection_reason": None,
            "published_at": raw_results[0]["published_at"],
            "magnitude_flags": [],
            "raw_metadata": {"locale": "en"},
        },
        {
            "id": "raw-0002",
            "url": raw_results[1]["url"],
            "canonical_url": raw_results[1]["canonical_url"],
            "title": raw_results[1]["title"],
            "source": raw_results[1]["source_domain"],
            "snippet": raw_results[1]["snippet"],
            "query_used": raw_results[1]["query_used"],
            "engine": raw_results[1]["engine"],
            "date_source": raw_results[1]["date_source"],
            "verification_status": "verified",
            "rejection_reason": None,
            "published_at": raw_results[1]["published_at"],
            "magnitude_flags": [],
            "raw_metadata": {"locale": "en"},
        },
    ]
    with open(run_dir / "verified.jsonl", "w") as f:
        for row in verified_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    articles = [
        {
            "id": "a001",
            "url": "https://news.skhynix.com/hbm4",
            "canonical_url": "https://news.skhynix.com/hbm4",
            "title": "SK hynix HBM4 Mass Production",
            "source": "SK hynix Newsroom",
            "source_type": "official",
            "source_locale": "en",
            "published_at": "2026-05-30T09:00:00+08:00",
            "date_source": "url_path",
            "fetched_at": "2026-05-30T10:00:00+08:00",
            "content_hash": "hash-a001",
            "entities": ["SK hynix"],
            "terms": ["HBM4"],
            "numeric_claims": [],
            "verification_status": "verified",
            "rejection_reason": None,
            "discovery_mode": "collector",
            "query_dimension": "official_sources",
            "artifact_type": "news_article",
            "cluster_id": "sc-storage-0001",
            "event_thread_id": None,
            "snippet": "Mass production of HBM4 begins.",
        },
        {
            "id": "a002",
            "url": "https://semiconductor-today.com/samsung-hbm4",
            "canonical_url": "https://semiconductor-today.com/samsung-hbm4",
            "title": "Samsung ships HBM4 to NVIDIA",
            "source": "Semiconductor Today",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2026-05-30T11:00:00+08:00",
            "date_source": "search_api",
            "fetched_at": "2026-05-30T11:30:00+08:00",
            "content_hash": "hash-a002",
            "entities": ["Samsung", "NVIDIA"],
            "terms": ["HBM4"],
            "numeric_claims": [],
            "verification_status": "verified",
            "rejection_reason": None,
            "discovery_mode": "baseline_seed",
            "query_dimension": "technology",
            "artifact_type": "news_article",
            "cluster_id": "sc-storage-0001",
            "event_thread_id": None,
            "snippet": "HBM4 samples shipped to NVIDIA.",
        },
    ]
    with open(run_dir / "articles.jsonl", "w") as f:
        for article in articles:
            f.write(json.dumps(article, ensure_ascii=False) + "\n")

    _write_json(run_dir / "clusters.json", {
        "date": "2026-05-30",
        "domain": "storage",
        "total_articles": 2,
        "clustered_articles": 2,
        "clusters": [
            {
                "id": "sc-storage-0001",
                "created": "2026-05-30",
                "canonical_title": "HBM4 Production Milestones",
                "canonical_summary": "Two HBM4 supply-chain signals surfaced.",
                "article_ids": ["a001", "a002"],
                "article_count": 2,
                "confidence": "high",
                "confidence_score": 0.8,
                "source_types": ["official", "media"],
                "locales": ["en"],
                "source_domains": ["news.skhynix.com", "semiconductor-today.com"],
                "canonical_urls": [
                    "https://news.skhynix.com/hbm4",
                    "https://semiconductor-today.com/samsung-hbm4",
                ],
                "entities": ["Samsung", "SK hynix", "NVIDIA"],
                "terms": ["HBM4"],
            }
        ],
        "unclustered": 0,
    })
    _write_json(run_dir / "raw.stats.json", {
        "date": "2026-05-30",
        "total_raw": 2,
        "total_curated": 2,
        "by_engine": {"direct_fetch:sk-hynix-newsroom": 1, "tavily": 1},
        "by_locale": {"en": 2},
        "by_source_type": {"official": 1, "media": 1},
        "queries": [
            {
                "query_id": "q-storage-001",
                "engine_used": "tavily",
                "status": "success",
                "results_count": 1,
                "locale": "en",
                "intent": "detection",
                "dimension": "technology",
                "query_text": "Samsung HBM4 NVIDIA",
                "retries": 0,
                "latency_ms": 10.0,
                "error": None,
            },
            {
                "query_id": "collector-sk-hynix-newsroom",
                "engine_used": "direct_fetch:sk-hynix-newsroom",
                "status": "success",
                "results_count": 1,
                "locale": "en",
                "intent": "collector",
                "dimension": "official_sources",
                "query_text": "collector source",
                "include_domains": ["news.skhynix.com"],
                "retries": 0,
                "latency_ms": 12.5,
                "error": None,
            },
        ],
        "diagnostics": {
            "raw_by_locale": {"en": 2},
            "curated_by_locale": {"en": 2},
            "raw_by_source_type": {"official": 1, "media": 1},
            "curated_by_source_type": {"official": 1, "media": 1},
            "raw_by_dimension": {"technology": 1, "official_sources": 1},
            "curated_by_dimension": {"technology": 1, "official_sources": 1},
            "dimension_coverage": [
                {"dimension": "official_sources", "queries": 1, "raw": 1, "curated": 1},
                {"dimension": "technology", "queries": 1, "raw": 1, "curated": 1},
            ],
            "locale_coverage": [
                {"locale": "en", "queries": 2, "raw": 2, "curated": 2},
            ],
            "source_type_gaps": [],
            "domain_filter_coverage": [
                {
                    "include_domain": "news.skhynix.com",
                    "queries": 1,
                    "failed_queries": 0,
                    "raw": 1,
                    "curated": 1,
                },
            ],
            "top_source_domains": [
                {"domain": "news.skhynix.com", "raw": 1, "curated": 1},
                {"domain": "semiconductor-today.com", "raw": 1, "curated": 1},
            ],
            "low_yield_queries": [],
        },
    })
    _write_json(run_dir / "collector_stats.json", {
        "domain": "storage",
        "date": "2026-05-30",
        "total_results": 1,
        "sources": [
            {
                "source": "sk-hynix-newsroom",
                "access": "direct_fetch",
                "status": "ok",
                "hits": 1,
                "selected": 1,
                "duration_ms": 12.5,
                "dated": 1,
            }
        ],
    })
    _write_json(run_dir / "event-threads.json", {
        "causal_edges": [],
        "judgments": [],
    })
    (run_dir / "briefing.html").write_text(
        "<!doctype html><html><body><h1>Storage Daily Briefing</h1></body></html>"
    )

    manifest_path = run_dir / "run_manifest.json"
    _write_json(manifest_path, {
        "domain": "storage",
        "date": "2026-05-30",
        "status": "ok",
        "stages": [
            {"stage": "search", "status": "success", "output": str(run_dir / "raw.json")},
            {"stage": "enrich", "status": "success", "output": str(run_dir / "enriched.json")},
            {"stage": "verify", "status": "success", "output": str(run_dir / "verified.jsonl")},
            {"stage": "normalize", "status": "success", "output": str(run_dir / "articles.jsonl")},
            {"stage": "cluster", "status": "success", "output": str(run_dir / "clusters.json")},
            {"stage": "render", "status": "success", "output": str(run_dir / "briefing.html")},
            {"stage": "manifest", "status": "success", "output": str(manifest_path)},
        ],
        "outputs": {
            "raw": str(run_dir / "raw.json"),
            "enriched": str(run_dir / "enriched.json"),
            "verified": str(run_dir / "verified.jsonl"),
            "articles": str(run_dir / "articles.jsonl"),
            "clusters": str(run_dir / "clusters.json"),
            "briefing_html": str(run_dir / "briefing.html"),
            "run_manifest": str(manifest_path),
        },
        "summary": {"articles": 2, "clusters": 1},
    })
    return run_dir


@pytest.fixture
def current_run_dir(tmp_path) -> Path:
    run_dir = _find_latest_run_dir("storage")
    if run_dir is None:
        return _write_golden_run_dir(tmp_path / "storage" / "data" / "2026-05-30")
    return run_dir


class TestPathDiscovery:
    def test_find_latest_run_dir_uses_current_layout(self, tmp_path, monkeypatch):
        root = tmp_path / "out"
        (root / "storage" / "data" / "2026-05-29").mkdir(parents=True)
        latest = root / "storage" / "data" / "2026-05-30"
        latest.mkdir(parents=True)
        (root / "storage" / "data" / "story-tracking").mkdir()

        monkeypatch.setattr(sys.modules[__name__], "_output_root", lambda: root)

        assert _find_latest_run_dir("storage") == latest


class TestJsonParseable:
    def test_articles_jsonl_is_valid(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "articles.jsonl"
        assert path.exists(), f"{path} not found"
        assert isinstance(_load_jsonl(path), list)

    def test_articles_match_contract_schema(self, current_run_dir):
        schema = _contract_schema("article_record.json")
        for row in _load_jsonl(current_run_dir / "articles.jsonl"):
            validate(row, schema)

    def test_clusters_json_is_valid(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "clusters.json"
        assert path.exists(), f"{path} not found"
        clusters = _load_clusters(path)
        assert all("id" in c for c in clusters)

    def test_clusters_match_contract_schema(self, current_run_dir):
        schema = _contract_schema("story_cluster.json")
        for cluster in _load_clusters(current_run_dir / "clusters.json"):
            validate(cluster, schema)

    def test_raw_stats_json_is_valid_if_present(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "raw.stats.json"
        if not path.exists():
            pytest.skip("No raw.stats.json")
        schema = _contract_schema("raw_search_stats.json")
        data = json.loads(path.read_text())
        validate(data, schema)

    def test_raw_json_matches_contract_if_present(self, current_run_dir):
        path = current_run_dir / "raw.json"
        if not path.exists():
            pytest.skip("No raw.json")
        schema = _contract_schema("raw_search_result.json")
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        for row in data:
            validate(row, schema)

    def test_enriched_json_preserves_raw_identity_if_present(self, current_run_dir):
        raw_path = current_run_dir / "raw.json"
        enriched_path = current_run_dir / "enriched.json"
        if not raw_path.exists() or not enriched_path.exists():
            pytest.skip("No raw/enriched pair")

        raw_rows = json.loads(raw_path.read_text())
        enriched_rows = json.loads(enriched_path.read_text())
        assert len(enriched_rows) == len(raw_rows)
        raw_urls = {row["canonical_url"] for row in raw_rows if row.get("canonical_url")}
        enriched_urls = {row["canonical_url"] for row in enriched_rows if row.get("canonical_url")}
        assert raw_urls <= enriched_urls

    def test_verified_jsonl_matches_contract_if_present(self, current_run_dir):
        path = current_run_dir / "verified.jsonl"
        if not path.exists():
            pytest.skip("No verified.jsonl")
        schema = _contract_schema("verified_article.json")
        for row in _load_jsonl(path):
            validate(row, schema)

    def test_collector_stats_json_is_valid_if_present(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "collector_stats.json"
        if not path.exists():
            pytest.skip("No collector_stats.json")
        schema = _contract_schema("collector_stats.json")
        data = json.loads(path.read_text())
        validate(data, schema)
        assert "sources" in data
        assert isinstance(data["sources"], list)

    def test_run_manifest_json_is_valid_if_present(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "run_manifest.json"
        if not path.exists():
            pytest.skip("No run_manifest.json")
        data = json.loads(path.read_text())
        assert data.get("domain") == "storage"
        assert data.get("date") == run_dir.name
        assert isinstance(data.get("stages", []), list)


class TestCrossReferenceIntegrity:
    def test_article_ids_in_clusters_exist(self, current_run_dir):
        run_dir = current_run_dir
        articles_path = run_dir / "articles.jsonl"
        clusters_path = run_dir / "clusters.json"
        assert articles_path.exists(), f"{articles_path} not found"
        assert clusters_path.exists(), f"{clusters_path} not found"

        article_ids = {row["id"] for row in _load_jsonl(articles_path)}
        broken_refs = []
        for cluster in _load_clusters(clusters_path):
            for aid in cluster.get("article_ids", []):
                if aid not in article_ids:
                    broken_refs.append(f"Cluster {cluster.get('id')}: article_id '{aid}' not in articles.jsonl")

        assert not broken_refs, "Broken article references:\n" + "\n".join(broken_refs)

    def test_run_manifest_outputs_exist_if_manifest_present(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "run_manifest.json"
        if not path.exists():
            pytest.skip("No run_manifest.json")

        manifest = json.loads(path.read_text())
        missing = []
        for stage in manifest.get("stages", []):
            output = stage.get("output")
            if output and stage.get("status") in {"success", "provided"}:
                if not Path(output).exists():
                    missing.append(f"{stage.get('stage')}: {output}")

        assert not missing, "Manifest points at missing outputs:\n" + "\n".join(missing)


class TestCollectorStatsConsistency:
    def test_collector_stats_have_current_fields(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "collector_stats.json"
        if not path.exists():
            pytest.skip("No collector_stats.json")

        data = json.loads(path.read_text())
        required = {"source", "access", "status", "hits", "selected", "duration_ms", "dated"}
        for i, source in enumerate(data.get("sources", []), 1):
            missing = required - set(source)
            assert not missing, f"collector source {i}: missing {sorted(missing)}"
            assert source["access"] in {"direct_fetch", "rss", "browser", "unknown"}
            assert source["status"] in {"ok", "empty", "error", "unsupported", "skipped"}


class TestEventThreadsIntegrity:
    def test_event_threads_is_valid_if_present(self, current_run_dir):
        run_dir = current_run_dir
        path = run_dir / "event-threads.json"
        if not path.exists():
            pytest.skip("No event-threads.json")

        data = json.loads(path.read_text())
        assert isinstance(data, dict)
        assert isinstance(data.get("causal_edges", []), list)
        assert isinstance(data.get("judgments", []), list)
