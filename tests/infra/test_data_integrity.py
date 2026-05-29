"""Layer 4: Data reference integrity — cross-file consistency checks.

Validates that cross-file references are consistent:
  - source-records cluster_id → exists in story-clusters
  - story-clusters article_ids → exist in articles
  - All JSON/JSONL files are valid parseable
  - trial-pool.json structure
"""

import json
import os
from pathlib import Path

import pytest


# ── Locate data ─────────────────────────────────────────────

def _output_root():
    # Walk up from this file to find config.yaml
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        cfg_path = os.path.join(current, "config.yaml")
        if os.path.exists(cfg_path):
            import yaml
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f)
            return Path(os.path.expanduser(cfg.get("output_dir", os.path.expanduser("~/WorkSpace/Stratum"))))
        current = os.path.dirname(current)
    return Path(os.path.expanduser("~/WorkSpace/Stratum"))


def _find_latest_date_subdir(channel, subdir):
    base = _output_root() / channel / "data" / subdir
    if not base.exists():
        return None
    dirs = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
    return dirs[0] if dirs else None


# ── JSON/JSONL validity ────────────────────────────────────

class TestJsonParseable:
    """All data files are valid JSON/JSONL."""

    def test_articles_jsonl_is_valid(self):
        d = _find_latest_date_subdir("storage", "articles")
        if d is None:
            pytest.skip("No articles data")
        path = d / "articles.jsonl"
        assert path.exists(), f"{path} not found"

        with open(path) as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    pytest.fail(f"articles.jsonl line {i}: invalid JSON — {e}")

    def test_story_clusters_json_is_valid(self):
        d = _find_latest_date_subdir("storage", "story-clusters")
        if d is None:
            pytest.skip("No story-clusters data")
        path = d / "story-clusters.json"
        assert path.exists()

        with open(path) as f:
            data = json.load(f)
        assert "clusters" in data
        assert isinstance(data["clusters"], list)

    def test_source_records_jsonl_is_valid(self):
        d = _find_latest_date_subdir("storage", "sources")
        if d is None:
            pytest.skip("No source-records data")
        path = d / "source-records.jsonl"
        assert path.exists()

        with open(path) as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    pytest.fail(f"source-records.jsonl line {i}: invalid JSON — {e}")

    def test_trial_pool_is_valid(self):
        path = _output_root() / "storage" / "data" / "sources" / "trial-pool.json"
        if not path.exists():
            pytest.skip("No trial-pool.json")
        with open(path) as f:
            data = json.load(f)
        assert "pools" in data or "entries" in data, "trial-pool.json missing 'pools' or 'entries'"
        assert "version" in data


# ── Cross-reference integrity ──────────────────────────────

class TestCrossReferenceIntegrity:
    """References between data files are consistent."""

    def test_cluster_ids_in_source_records_exist(self):
        """source-records cluster_id references actual story clusters."""
        articles_dir = _find_latest_date_subdir("storage", "articles")
        clusters_dir = _find_latest_date_subdir("storage", "story-clusters")
        sources_dir = _find_latest_date_subdir("storage", "sources")

        if any(d is None for d in [articles_dir, clusters_dir, sources_dir]):
            pytest.skip("Missing one or more data dirs")

        # Load cluster IDs
        with open(clusters_dir / "story-clusters.json") as f:
            clusters_data = json.load(f)
        cluster_ids = {c["id"] for c in clusters_data.get("clusters", [])}

        # Check source-records references
        records_path = sources_dir / "source-records.jsonl"
        broken_refs = []
        with open(records_path) as f:
            for line in f:
                record = json.loads(line)
                cid = record.get("cluster_id")
                if cid and cid not in cluster_ids:
                    broken_refs.append(f"source-record {record.get('id')}: cluster_id '{cid}' not found")

        assert not broken_refs, f"Broken cluster references:\n" + "\n".join(broken_refs)

    def test_article_ids_in_clusters_exist(self):
        """story-clusters article_ids reference actual articles."""
        articles_dir = _find_latest_date_subdir("storage", "articles")
        clusters_dir = _find_latest_date_subdir("storage", "story-clusters")

        if any(d is None for d in [articles_dir, clusters_dir]):
            pytest.skip("Missing data dirs")

        # Load article IDs
        article_ids = set()
        if (articles_dir / "articles.jsonl").exists():
            with open(articles_dir / "articles.jsonl") as f:
                for line in f:
                    record = json.loads(line)
                    article_ids.add(record["id"])

        # Check cluster references
        with open(clusters_dir / "story-clusters.json") as f:
            data = json.load(f)

        broken_refs = []
        for c in data.get("clusters", []):
            for aid in c.get("article_ids", []):
                if aid not in article_ids:
                    broken_refs.append(f"Cluster {c['id']}: article_id '{aid}' not in articles.jsonl")
            # Also check duplicate_ids
            for aid in c.get("duplicate_ids", []):
                if aid not in article_ids:
                    broken_refs.append(f"Cluster {c['id']}: duplicate_id '{aid}' not in articles.jsonl")

        assert not broken_refs, f"Broken article references:\n" + "\n".join(broken_refs)


# ── Source record consistency ───────────────────────────────

class TestSourceRecordConsistency:
    """Source records have consistent fields."""

    def test_source_records_have_required_fields(self):
        d = _find_latest_date_subdir("storage", "sources")
        if d is None:
            pytest.skip("No source-records data")

        required = {"id", "source", "source_type", "source_locale", "signal_type", "date"}
        path = d / "source-records.jsonl"

        with open(path) as f:
            for i, line in enumerate(f, 1):
                record = json.loads(line)
                for field in required:
                    assert field in record, f"Line {i}: missing '{field}' in {record.get('id', '?')}"

    def test_source_types_are_valid(self):
        d = _find_latest_date_subdir("storage", "sources")
        if d is None:
            pytest.skip("No source-records data")

        valid_types = {"official", "media", "analyst", "blog", "social", "financial",
                       "patent_db", "academic", "hiring_platform"}
        path = d / "source-records.jsonl"

        with open(path) as f:
            for line in f:
                record = json.loads(line)
                st = record.get("source_type")
                assert st in valid_types, f"Record {record.get('id')}: invalid source_type '{st}'"

    def test_source_locales_match_pattern(self):
        d = _find_latest_date_subdir("storage", "sources")
        if d is None:
            pytest.skip("No source-records data")

        import re
        locale_pat = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
        path = d / "source-records.jsonl"

        with open(path) as f:
            for line in f:
                record = json.loads(line)
                loc = record.get("source_locale", "")
                assert locale_pat.match(loc), f"Record {record.get('id')}: invalid locale '{loc}'"


# ── Event threads integrity ────────────────────────────────

class TestEventThreadsIntegrity:
    """Event threads file is valid JSON and has expected structure."""

    def test_event_threads_is_valid(self):
        path = _output_root() / "storage" / "data" / "event-threads" / "event-threads.json"
        if not path.exists():
            pytest.skip("No event-threads.json")

        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

        for tid, thread in data.items():
            assert "title" in thread, f"Thread {tid}: missing 'title'"
            assert "timeline" in thread, f"Thread {tid}: missing 'timeline'"
            assert isinstance(thread["timeline"], list)
