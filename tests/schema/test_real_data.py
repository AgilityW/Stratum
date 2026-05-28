"""Layer 1: Schema contract tests — validate real output data against JSON schemas.

Tests actual pipeline output files (if they exist) against ArticleRecord and StoryCluster schemas.
Gracefully skips when data files don't exist (e.g., fresh clone, no pipeline run yet).
"""

import json
import os
from pathlib import Path

import pytest
import jsonschema


# ── Locate real data ───────────────────────────────────────

def _output_root():
    """Read output_dir from config.yaml, fallback to env default."""
    cfg_path = Path.home() / "ProjectSpace" / "Stratum" / "config.yaml"
    if cfg_path.exists():
        import yaml
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        return Path(os.path.expanduser(cfg.get("output_dir", "~/WorkSpace/Stratum")))
    return Path.home() / "WorkSpace" / "Stratum"


def _find_latest_data_dir(channel, subdir):
    """Find the latest date subdirectory under data/{subdir}/ that has data files."""
    base = _output_root() / channel / "data" / subdir
    if not base.exists():
        return None
    dirs = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
    for d in dirs:
        return d  # return most recent
    return None


# ── Load schemas ────────────────────────────────────────────

@pytest.fixture
def article_schema():
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "article-record.schema.json"
    with open(schema_path) as f:
        return json.load(f)


@pytest.fixture
def cluster_schema():
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "story-cluster.schema.json"
    with open(schema_path) as f:
        return json.load(f)


# ── Schema tests ────────────────────────────────────────────

class TestArticleRecordSchema:
    """Validate real articles.jsonl against schema."""

    @pytest.fixture
    def articles_path(self):
        d = _find_latest_data_dir("storage", "articles")
        if d:
            p = d / "articles.jsonl"
            if p.exists():
                return p
        return None

    def test_schema_is_valid_json(self, article_schema):
        """Schema itself is parseable and has required fields."""
        assert "$schema" in article_schema
        assert article_schema["type"] == "object"
        assert "required" in article_schema

    def test_real_articles_validate(self, article_schema, articles_path):
        """Every record in the latest articles.jsonl passes schema validation."""
        if articles_path is None:
            pytest.skip("No articles.jsonl found — run pipeline first")

        errors = []
        with open(articles_path) as f:
            for i, line in enumerate(f, 1):
                try:
                    record = json.loads(line)
                    jsonschema.validate(record, article_schema)
                except (json.JSONDecodeError, jsonschema.ValidationError) as e:
                    errors.append(f"Line {i}: {e}")

        assert not errors, f"Schema violations:\n" + "\n".join(errors)

    def test_required_fields_present(self, article_schema, articles_path):
        """Real data has all required fields non-empty."""
        if articles_path is None:
            pytest.skip("No articles.jsonl found")

        required = article_schema["required"]
        with open(articles_path) as f:
            for i, line in enumerate(f, 1):
                record = json.loads(line)
                for field in required:
                    assert field in record, f"Line {i}: missing required field '{field}'"
                    assert record[field] is not None, f"Line {i}: required field '{field}' is None"


class TestStoryClusterSchema:
    """Validate real story-clusters.json against schema."""

    @pytest.fixture
    def clusters_path(self):
        d = _find_latest_data_dir("storage", "story-clusters")
        if d:
            p = d / "story-clusters.json"
            if p.exists():
                return p
        return None

    def test_schema_is_valid_json(self, cluster_schema):
        assert "$schema" in cluster_schema
        assert cluster_schema["type"] == "object"

    def test_real_clusters_validate(self, cluster_schema, clusters_path):
        """The cluster wrapper and each cluster pass schema validation."""
        if clusters_path is None:
            pytest.skip("No story-clusters.json found")

        with open(clusters_path) as f:
            wrapper = json.load(f)

        # Validate the wrapper itself
        jsonschema.validate(wrapper, cluster_schema)

        # Validate each cluster entry
        clusters = wrapper.get("clusters", [])
        assert len(clusters) > 0, "No clusters in story-clusters.json"

        errors = []
        for cluster in clusters:
            try:
                jsonschema.validate(cluster, cluster_schema)
            except jsonschema.ValidationError as e:
                errors.append(f"Cluster {cluster.get('id', '?')}: {e}")

        assert not errors, f"Schema violations:\n" + "\n".join(errors)

    def test_cluster_novelty_values(self, clusters_path):
        """All clusters have valid novelty enum values."""
        if clusters_path is None:
            pytest.skip("No story-clusters.json found")

        valid = {"first_disclosure", "update", "rehash", "rumor", "confirmation", "contradiction"}
        with open(clusters_path) as f:
            data = json.load(f)

        for c in data.get("clusters", []):
            assert c["novelty"] in valid, f"Cluster {c['id']}: invalid novelty '{c['novelty']}'"

    def test_cluster_confidence_values(self, clusters_path):
        """All clusters have valid confidence enum values."""
        if clusters_path is None:
            pytest.skip("No story-clusters.json found")

        valid = {"A", "B", "C", "D"}
        with open(clusters_path) as f:
            data = json.load(f)

        for c in data.get("clusters", []):
            assert c["confidence"] in valid, f"Cluster {c['id']}: invalid confidence '{c['confidence']}'"

    def test_cluster_ids_match_date(self, clusters_path):
        """Cluster IDs contain the correct date."""
        if clusters_path is None:
            pytest.skip("No story-clusters.json found")

        with open(clusters_path) as f:
            data = json.load(f)

        for c in data.get("clusters", []):
            cid = c["id"]  # sc-YYYY-MM-DD-NNN
            assert cid.startswith(f"sc-{c['date']}-"), f"Cluster {cid}: ID date mismatch with {c['date']}"
