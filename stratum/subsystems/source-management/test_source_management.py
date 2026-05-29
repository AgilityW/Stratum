"""Tests for source-management subsystem."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pytest
import json
import os
import tempfile
from pathlib import Path

from recorder import generate_records, build_article_cluster_map, extract_domain
from profiler import (
    init_profile, compute_metrics, update_profile, save_profile,
    load_profile, process_records,
)
from trial import (
    init_trial_pool, load_trial_pool, save_trial_pool,
    add_candidate, track_samples, evaluate_source, process_evaluations,
    PROMOTE_THRESHOLD,
)


class TestRecorder:
    def test_extract_domain(self):
        assert extract_domain("https://reuters.com/tech/article") == "reuters.com"
        assert extract_domain("https://www.samsung.com/news") == "samsung.com"
        assert extract_domain("") == ""

    def test_build_cluster_map(self):
        clusters = [
            {"id": "sc-1", "novelty": "first_disclosure", "article_ids": ["a1", "a2"]},
            {"id": "sc-2", "novelty": "update", "article_ids": ["a3"]},
        ]
        amap = build_article_cluster_map(clusters)
        assert amap["a1"] == ("sc-1", "first_disclosure")
        assert amap["a3"] == ("sc-2", "update")

    def test_generate_records(self):
        articles = [
            {"id": "a1", "url": "https://reuters.com/tech", "source_type": "media",
             "source_locale": "en", "artifact_type": "news_article"},
            {"id": "a2", "url": "https://samsung.com/news", "source_type": "official",
             "source_locale": "en", "artifact_type": "product_announcement"},
        ]
        clusters = [
            {"id": "sc-1", "novelty": "first_disclosure", "article_ids": ["a1", "a2"]},
        ]
        records = generate_records(articles, clusters, "2026-05-28")
        assert len(records) == 2
        assert records[0]["role"] == "first_disclosure"
        assert records[0]["signal_type"] == "text_news"

    def test_dedup_same_domain_cluster(self):
        articles = [
            {"id": "a1", "url": "https://reuters.com/a", "source_type": "media",
             "source_locale": "en", "artifact_type": "news_article"},
            {"id": "a2", "url": "https://reuters.com/b", "source_type": "media",
             "source_locale": "en", "artifact_type": "news_article"},
        ]
        clusters = [
            {"id": "sc-1", "novelty": "update", "article_ids": ["a1", "a2"]},
        ]
        records = generate_records(articles, clusters, "2026-05-28")
        assert len(records) == 1  # deduped


class TestProfiler:
    def test_init_profile(self):
        recs = [{"source_type": "media", "source_locale": "en", "signal_type": "text_news"}]
        profile = init_profile("reuters.com", recs)
        assert profile["source"] == "reuters.com"
        assert profile["status"] == "active"

    def test_compute_metrics(self):
        recs = [
            {"role": "first_disclosure", "cluster_id": "sc-1"},
            {"role": "first_disclosure", "cluster_id": "sc-1"},
            {"role": "rehash", "cluster_id": "sc-2"},
            {"role": "update", "cluster_id": "sc-3"},
        ]
        metrics = compute_metrics(recs)
        assert metrics["novelty_ratio"] == 0.5
        assert metrics["signal_noise_ratio"] == 0.75

    def test_update_profile_ema(self):
        profile = init_profile("test.com", [{"source_type": "media"}])
        metrics = {"novelty_ratio": 0.8, "exclusivity": 0.5, "signal_noise_ratio": 0.9, "total": 10}
        profile, alerts = update_profile(profile, metrics, "2026-05-28")
        assert profile["current"]["novelty_ratio"] == pytest.approx(0.8)
        assert profile["current"]["total_records"] == 10

    def test_degradation_detection(self):
        profile = init_profile("test.com", [{"source_type": "media"}])
        profile["current"] = {"novelty_ratio": 0.9, "verifiability": 0.5,
                              "exclusivity": 0.5, "signal_noise_ratio": 0.9, "total_records": 100}
        metrics = {"novelty_ratio": 0.3, "exclusivity": 0.5, "signal_noise_ratio": 0.9, "total": 10}
        profile, alerts = update_profile(profile, metrics, "2026-05-28")
        assert len(alerts) == 1
        assert alerts[0]["type"] == "novelty_drop"

    def test_save_and_load(self, tmp_path):
        profile = init_profile("test.com", [{"source_type": "media"}])
        save_profile(str(tmp_path), profile)
        loaded = load_profile(str(tmp_path), "test.com")
        assert loaded["source"] == "test.com"

    def test_process_records(self, tmp_path):
        records = [
            {"source_domain": "a.com", "source": "a.com", "role": "first_disclosure",
             "cluster_id": "sc-1"},
            {"source_domain": "a.com", "source": "a.com", "role": "update",
             "cluster_id": "sc-2"},
        ]
        stats = process_records(records, str(tmp_path), "2026-05-28")
        assert stats["updated"] == 1
        assert stats["new"] == 1


class TestTrialManager:
    def test_init_pool(self):
        pool = init_trial_pool()
        assert pool["version"] == "2.0"
        assert pool["entries"] == []

    def test_add_candidate(self):
        pool = init_trial_pool()
        pool = add_candidate(pool, "newsource.com", "media", "en",
                            "2026-05-28", query="site:newsource.com")
        assert len(pool["entries"]) == 1
        assert pool["entries"][0]["status"] == "collecting"

    def test_skip_duplicate(self):
        pool = init_trial_pool()
        pool = add_candidate(pool, "dup.com", "media", "en", "2026-05-28")
        pool = add_candidate(pool, "dup.com", "media", "en", "2026-05-29")
        assert len(pool["entries"]) == 1

    def test_track_samples_triggers_eval(self):
        pool = init_trial_pool()
        pool = add_candidate(pool, "test.com", "media", "en", "2026-05-28",
                            min_samples=2)
        records = [
            {"source": "test.com", "trial": True},
            {"source": "test.com", "trial": True},
        ]
        pool, triggered = track_samples(pool, records)
        assert pool["entries"][0]["sample_count"] == 2
        assert len(triggered) == 1
        assert triggered[0]["status"] == "evaluating"

    def test_evaluate_promotes_high_score(self):
        entry = {"source": "good.com"}
        src_records = [
            {"role": "first_disclosure", "verified_by": "reuters", "claims_contributed": ["claim1", "claim2"]},
            {"role": "first_disclosure", "verified_by": "bloomberg", "claims_contributed": ["claim3"]},
        ]
        all_records = src_records + [
            {"role": "update", "claims_contributed": ["claim1"]},  # shared claim
        ]
        entry = evaluate_source(entry, src_records, all_records)
        assert entry["recommendation"] == "promote"
        assert entry["eval_score"] >= PROMOTE_THRESHOLD

    def test_evaluate_archives_low_score(self):
        entry = {"source": "bad.com"}
        src_records = [
            {"role": "rehash", "claims_contributed": []},
            {"role": "rehash", "claims_contributed": []},
        ]
        entry = evaluate_source(entry, src_records, src_records)
        assert entry["recommendation"] == "archive"
        assert entry["eval_score"] < PROMOTE_THRESHOLD

    def test_save_load_pool(self, tmp_path):
        pool = init_trial_pool()
        pool = add_candidate(pool, "test.com", "media", "en", "2026-05-28")
        path = os.path.join(str(tmp_path), "trial-pool.json")
        save_trial_pool(pool, path)
        loaded = load_trial_pool(path)
        assert len(loaded["entries"]) == 1
        assert loaded["entries"][0]["source"] == "test.com"
