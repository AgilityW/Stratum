"""Integration test — full pipeline with mock data."""
import json
import os
import tempfile
import pytest
import subprocess
import sys

PROJECT_ROOT = os.path.expanduser("~/ProjectSpace/Stratum")
STAGES_DIR = os.path.join(PROJECT_ROOT, "stratum", "stages")
DOMAIN_CONFIG = os.path.join(PROJECT_ROOT, "domains", "storage", "domain.yaml")


def make_raw_results():
    """Create realistic raw search results for integration testing."""
    return [
        {
            "url": "https://reuters.com/technology/samsung-hbm4",
            "title": "Samsung ships HBM4 samples to NVIDIA",
            "snippet": "Samsung Electronics announced it has begun shipping HBM4 memory samples to NVIDIA Corp.",
            "datePublished": "2026-05-28",
            "engine": "tavily",
            "query_used": "Samsung HBM4",
        },
        {
            "url": "https://semiconductor.samsung.com/newsroom/hbm4",
            "title": "Samsung Begins Mass Production of HBM4",
            "snippet": "Samsung Electronics announced mass production of its 5th-generation HBM4 memory.",
            "datePublished": "2026-05-28",
            "engine": "bocha",
            "query_used": "三星 HBM4",
        },
        {
            "url": "https://trendforce.com/news/dram-price-q2-2026",
            "title": "DRAM Contract Prices Rise 15% in Q2 2026",
            "snippet": "DRAM contract prices increased 15% QoQ driven by AI server demand.",
            "datePublished": "2026-05-27",
            "engine": "tavily",
            "query_used": "DRAM price",
        },
        {
            "url": "https://youtube.com/watch?v=123",
            "title": "Memory chip review",
            "snippet": "Review of latest memory chips.",
            "datePublished": "2026-05-28",
            "engine": "tavily",
            "query_used": "memory chip",
        },
    ]


class TestFullPipeline:
    """End-to-end pipeline: enrich → verify → normalize → cluster."""

    def test_pipeline_end_to_end(self, tmp_path):
        """Run all deterministic stages and verify output consistency."""
        raw_input = tmp_path / "raw.json"
        enriched = tmp_path / "enriched.json"
        verified = tmp_path / "verified.jsonl"
        articles = tmp_path / "articles.jsonl"
        clusters = tmp_path / "clusters.json"

        # Write raw input
        with open(raw_input, "w") as f:
            json.dump(make_raw_results(), f)

        # Stage 2: Enrich
        result = subprocess.run([
            sys.executable,
            os.path.join(STAGES_DIR, "enrich", "enrich.py"),
            "--input", str(raw_input),
            "--output", str(enriched),
            "--date", "2026-05-28",
        ], capture_output=True, text=True)
        assert result.returncode == 0, f"Enrich failed: {result.stderr}"
        assert enriched.exists()

        # Stage 3: Verify
        result = subprocess.run([
            sys.executable,
            os.path.join(STAGES_DIR, "verify", "verify.py"),
            "--input", str(enriched),
            "--output", str(verified),
            "--date", "2026-05-28",
            "--domain", DOMAIN_CONFIG,
        ], capture_output=True, text=True)
        assert result.returncode == 0, f"Verify failed: {result.stderr}"
        assert verified.exists()

        # Check verification results
        verified_lines = []
        with open(verified) as f:
            for line in f:
                if line.strip():
                    verified_lines.append(json.loads(line))

        assert len(verified_lines) == 4
        statuses = [v["verification_status"] for v in verified_lines]
        assert "verified" in statuses
        assert "rejected" in statuses  # youtube.com should be rejected

        # Stage 4: Normalize
        result = subprocess.run([
            sys.executable,
            os.path.join(STAGES_DIR, "normalize", "normalize.py"),
            "--input", str(verified),
            "--output", str(articles),
            "--domain", DOMAIN_CONFIG,
        ], capture_output=True, text=True)
        assert result.returncode == 0, f"Normalize failed: {result.stderr}"
        assert articles.exists()

        # Check normalization
        article_lines = []
        with open(articles) as f:
            for line in f:
                if line.strip():
                    article_lines.append(json.loads(line))

        assert len(article_lines) >= 1  # at least some verified
        for a in article_lines:
            assert "entities" in a
            assert "terms" in a
            assert "source_type" in a
            assert "artifact_type" in a
            # Samsung + HBM should be in entities/terms for the first articles
            if "Samsung" in a["title"]:
                assert len(a["entities"]) > 0

        # Stage 5: Cluster
        if len(article_lines) >= 2:
            result = subprocess.run([
                sys.executable,
                os.path.join(STAGES_DIR, "cluster", "cluster.py"),
                "--input", str(articles),
                "--output", str(clusters),
                "--domain", DOMAIN_CONFIG,
                "--date", "2026-05-28",
            ], capture_output=True, text=True)
            assert result.returncode == 0, f"Cluster failed: {result.stderr}"
            assert clusters.exists()

            with open(clusters) as f:
                cluster_data = json.load(f)
            assert "clusters" in cluster_data
            assert "domain" in cluster_data

    def test_domain_config_loads(self):
        """Verify domain.yaml is parseable and has required sections."""
        import yaml
        with open(DOMAIN_CONFIG) as f:
            config = yaml.safe_load(f)

        # Domain metadata
        assert "domain" in config
        assert config["domain"]["id"] == "storage"

        # Pipeline config
        pipeline = config.get("pipeline", {})
        assert "blocklist" in pipeline, "Missing pipeline.blocklist"
        assert "source_classification" in pipeline, "Missing pipeline.source_classification"
        assert "flat_entities" in pipeline, "Missing pipeline.flat_entities"
        assert "flat_terms" in pipeline, "Missing pipeline.flat_terms"
        assert "source_aliases" in pipeline, "Missing pipeline.source_aliases"

    def test_no_hardcoded_domain_in_stages(self):
        """Verify that no stage file contains hardcoded domain-specific data."""
        import re
        domain_indicators = [
            "samsung.com", "skhynix.com", "micron.com",
            "trendforce.com", "storage chip", "存储芯片",
            "STORAGE_COMPANIES", "STORAGE_TERMS",
        ]

        stage_files = [
            os.path.join(STAGES_DIR, "enrich", "enrich.py"),
            os.path.join(STAGES_DIR, "verify", "verify.py"),
            os.path.join(STAGES_DIR, "normalize", "normalize.py"),
            os.path.join(STAGES_DIR, "cluster", "cluster.py"),
            os.path.join(STAGES_DIR, "validate", "validate.py"),
        ]

        for stage_file in stage_files:
            with open(stage_file) as f:
                content = f.read()

            for indicator in domain_indicators:
                # Skip lines that are comments or imports
                lines = content.split('\n')
                code_lines = [l for l in lines if not l.strip().startswith('#') and not l.strip().startswith('"')]
                code_content = '\n'.join(code_lines)

                if indicator in code_content:
                    # Check if it's in a docstring/comment
                    in_docstring = False
                    for line in lines:
                        if indicator in line:
                            if line.strip().startswith('#') or line.strip().startswith('"""'):
                                in_docstring = True
                                break
                    if not in_docstring:
                        pytest.fail(
                            f"{os.path.basename(stage_file)} contains hardcoded "
                            f"domain data: '{indicator}'. "
                            f"All domain data must be in domain.yaml."
                        )
