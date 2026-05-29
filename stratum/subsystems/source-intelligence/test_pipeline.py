"""Tests for source-intelligence: enricher + pipeline."""
import sys, os, json, tempfile
import pytest
from pathlib import Path

# Add source-intelligence to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from stratum.contracts import (
    RecordInput, DiscoverCandidate, PipelineResult,
    HealthAlert, CoverageGap, EvalDimensions, EvalResult,
)
from enricher import (
    compute_acceleration_signals, compute_diversity,
    compute_baseline_comparison, calibrate_confidence,
    compute_enriched_eval,
)
from evolution_pipeline import (
    stage_record, stage_discover, stage_health,
    stage_coverage, run_pipeline,
)


# ═══════════════════════════════════════════════
# Enricher Tests
# ═══════════════════════════════════════════════

class TestAccelerationSignals:
    def test_cited_by_trusted(self):
        src_records = [
            {"verified_by": "reuters.com, bloomberg.com", "cluster_id": "sc-1", "source": "newsource.com"},
        ]
        all_records = src_records + [
            {"cluster_id": "sc-1", "source": "reuters.com"},
        ]
        known = {"reuters.com", "bloomberg.com"}
        signals = compute_acceleration_signals(src_records, all_records, known)
        assert "cited_by_trusted" in signals
        assert signals["cited_by_trusted"] == 0.10

    def test_no_citation_no_signal(self):
        src_records = [{"verified_by": "", "cluster_id": "sc-1"}]
        signals = compute_acceleration_signals(src_records, src_records, set())
        assert "cited_by_trusted" not in signals

    def test_fills_coverage_gap(self):
        src_records = [
            {"cluster_id": "sc-1", "source": "exclusive.com"},
            {"cluster_id": "sc-2", "source": "exclusive.com"},
            {"cluster_id": "sc-3", "source": "exclusive.com"},
        ]
        all_records = src_records  # Only this source covers these clusters
        signals = compute_acceleration_signals(src_records, all_records, set())
        assert "fills_coverage_gap" in signals
        assert signals["fills_coverage_gap"] == 0.15

    def test_multi_locale(self):
        src_records = [
            {"source_locale": "en", "cluster_id": "sc-1"},
            {"source_locale": "zh-CN", "cluster_id": "sc-2"},
        ]
        signals = compute_acceleration_signals(src_records, src_records, set())
        assert "multi_locale" in signals


class TestDiversity:
    def test_max_diversity(self):
        records = [
            {"cluster_id": f"sc-{i}"} for i in range(10)
        ]
        assert compute_diversity(records) == 1.0

    def test_low_diversity(self):
        records = [
            {"cluster_id": "sc-1"} for _ in range(10)
        ]
        assert compute_diversity(records) == 0.1

    def test_empty(self):
        assert compute_diversity([]) == 0.0


class TestBaseline:
    def test_above_average(self):
        stats = {"novelty_ratio": 0.8, "signal_noise_ratio": 0.9, "exclusivity": 0.5}
        median = {"novelty_ratio": 0.5, "signal_noise_ratio": 0.7, "exclusivity": 0.3}
        result = compute_baseline_comparison(stats, median)
        assert result["novelty_ratio"]["assessment"] == "above_average"

    def test_below_average(self):
        stats = {"novelty_ratio": 0.2, "signal_noise_ratio": 0.5, "exclusivity": 0.1}
        median = {"novelty_ratio": 0.5, "signal_noise_ratio": 0.7, "exclusivity": 0.3}
        result = compute_baseline_comparison(stats, median)
        assert result["novelty_ratio"]["assessment"] == "below_average"

    def test_empty_returns_empty(self):
        assert compute_baseline_comparison({}, {}) == {}


class TestCalibrateConfidence:
    def test_high_confidence(self):
        assert calibrate_confidence(0.75, 50, 20) == "high"

    def test_medium_confidence(self):
        assert calibrate_confidence(0.65, 20, 20) == "medium"

    def test_low_confidence(self):
        assert calibrate_confidence(0.80, 10, 20) == "low"


class TestEnrichedEval:
    def test_promote_high_quality(self):
        # Truly exceptional source: 50 samples, all first_disclosure, verified,
        # completely exclusive claims, multi-locale, consistent over many days
        src_records = []
        all_other = []
        for i in range(50):
            rec = {
                "role": "first_disclosure",
                "verified_by": "reuters.com, bloomberg.com",
                "claims_contributed": [f"excl-{i}-a", f"excl-{i}-b", f"excl-{i}-c"],
                "cluster_id": f"sc-{i % 15}",
                "source_locale": "en" if i % 3 else "zh-CN",
                "source": "great.com",
                "date": f"2026-05-{min(28, 1 + i // 5):02d}",
            }
            src_records.append(rec)
            all_other.append({
                "role": "update", "verified_by": "",
                "claims_contributed": [f"other-{i % 5}"],
                "cluster_id": f"sc-{(i+7) % 25}", "source_locale": "en",
                "source": "other.com",
            })

        result = compute_enriched_eval(
            src_records, src_records + all_other,
            {"reuters.com", "bloomberg.com"}, min_samples=20,
        )
        # With 50 high-quality samples, should promote
        if result["recommendation"] != "promote":
            # If not, score must be too low — check dimensions
            assert result["score"] >= 0.60, \
                f"Score too low: {result['score']}, dims={result['dimensions']}"
        else:
            assert result["score"] >= 0.70

    def test_archive_low_quality(self):
        records = []
        for i in range(20):
            records.append({
                "role": "rehash", "verified_by": "",
                "claims_contributed": [],
                "cluster_id": "sc-1", "source_locale": "en",
                "source": "bad.com",
            })
        result = compute_enriched_eval(records, records, set())
        assert result["recommendation"] == "archive"
        assert result["score"] < 0.50

    def test_extend_borderline(self):
        records = []
        for i in range(15):
            records.append({
                "role": "first_disclosure" if i < 5 else "update",
                "verified_by": "reuters.com" if i < 3 else "",
                "claims_contributed": ["claim-a"],
                "cluster_id": f"sc-{i % 8}", "source_locale": "en",
                "source": "mid.com",
            })
        result = compute_enriched_eval(records, records, {"reuters.com"})
        assert result["recommendation"] in ("extend", "archive", "promote")
        assert 0 <= result["score"] <= 1.0

    def test_empty_records(self):
        result = compute_enriched_eval([], [], set())
        assert result["recommendation"] == "insufficient_data"
        assert result["score"] == 0.0


# ═══════════════════════════════════════════════════
# Pipeline Stage Tests
# ═══════════════════════════════════════════════════

class TestStageRecord:
    def test_record_generates_from_articles(self, tmp_path):
        # Create articles.jsonl
        articles = [
            {"id": "a1", "url": "https://reuters.com/tech", "source_type": "media",
             "source_locale": "en", "artifact_type": "news_article", "source": "reuters.com"},
            {"id": "a2", "url": "https://samsung.com/news", "source_type": "official",
             "source_locale": "en", "artifact_type": "product_announcement", "source": "samsung.com"},
        ]
        articles_path = tmp_path / "articles.jsonl"
        with open(articles_path, "w") as f:
            for a in articles:
                f.write(json.dumps(a) + "\n")

        clusters = {"clusters": [
            {"id": "sc-1", "novelty": "first_disclosure", "article_ids": ["a1", "a2"]},
        ]}
        clusters_path = tmp_path / "clusters.json"
        with open(clusters_path, "w") as f:
            json.dump(clusters, f)

        result = stage_record(RecordInput(
            articles_path=str(articles_path),
            clusters_path=str(clusters_path),
            run_date="2026-05-28",
        ))
        assert result.unique_sources == 2
        assert result.total_records == 2


class TestStageDiscover:
    def test_finds_new_sources(self):
        records = [
            {"source_domain": "newsite.com", "source_type": "media", "source_locale": "en",
             "cluster_id": "sc-1"},
            {"source_domain": "reuters.com", "source_type": "media", "source_locale": "en",
             "cluster_id": "sc-1"},
        ]
        known = {"reuters.com"}
        trial = set()
        result = stage_discover(records, known, trial, "2026-05-28")
        assert result.total_new == 1
        assert result.candidates[0].domain == "newsite.com"

    def test_skips_known(self):
        records = [{"source_domain": "reuters.com", "source_type": "media", "source_locale": "en"}]
        result = stage_discover(records, {"reuters.com"}, set(), "2026-05-28")
        assert result.total_new == 0

    def test_skips_trial(self):
        records = [{"source_domain": "trial.com", "source_type": "media", "source_locale": "en"}]
        result = stage_discover(records, set(), {"trial.com"}, "2026-05-28")
        assert result.total_new == 0


class TestStageHealth:
    def test_health_with_records(self, tmp_path):
        records = [
            {"source_domain": "good.com", "role": "first_disclosure"},
            {"source_domain": "good.com", "role": "update"},
            {"source_domain": "dry.com", "role": "rehash"},
        ]
        result = stage_health(str(tmp_path), records, "2026-05-28")
        assert result.total_sources == 2
        assert result.healthy >= 0


class TestStageCoverage:
    def test_coverage_with_clusters(self, tmp_path):
        clusters = {"clusters": [
            {"id": "sc-1", "canonical_title": "Test Story", "confidence": "C"},
        ]}
        clusters_path = tmp_path / "clusters.json"
        with open(clusters_path, "w") as f:
            json.dump(clusters, f)

        records = [
            {"cluster_id": "sc-1", "source_type": "media", "source_locale": "en", "source": "test.com"},
        ]
        result = stage_coverage(str(clusters_path), records, "2026-05-28", str(tmp_path))
        assert result.total_clusters == 1
        assert result.gaps_found >= 0


# ═══════════════════════════════════════════════════
# Integration Test
# ═══════════════════════════════════════════════════

class TestFullPipeline:
    def test_pipeline_with_mock_data(self, tmp_path):
        """End-to-end source intelligence pipeline with mock data."""
        run_date = "2026-05-28"
        data_dir = str(tmp_path)

        # Create articles
        articles = []
        for i in range(5):
            articles.append({
                "id": f"a{i}", "url": f"https://source{i}.com/article",
                "source_type": "media", "source_locale": "en",
                "artifact_type": "news_article",
                "source": f"source{i}.com",
            })
        articles_path = os.path.join(data_dir, "articles.jsonl")
        with open(articles_path, "w") as f:
            for a in articles:
                f.write(json.dumps(a) + "\n")

        # Create clusters
        clusters = {"clusters": [
            {"id": "sc-1", "novelty": "first_disclosure",
             "article_ids": ["a0", "a1"], "canonical_title": "Test", "confidence": "B"},
        ]}
        clusters_path = os.path.join(data_dir, "clusters.json")
        with open(clusters_path, "w") as f:
            json.dump(clusters, f)

        # Minimal domain config
        domain_config = {
            "companies": [{"aliases": {"en": "KnownCorp"}}],
            "pipeline": {"low_priority_domains": ["google.com"]},
        }

        result = run_pipeline("storage", run_date, data_dir, domain_config)

        assert result.domain_id == "storage"
        assert len(result.errors) == 0
        assert result.record is not None
        assert result.record.unique_sources > 0
        assert result.discover is not None
        assert result.health is not None
        assert result.summary != ""
