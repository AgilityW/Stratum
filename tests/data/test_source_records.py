"""Data integrity tests for collector_stats.json sidecar shape.

The old source-records artifact was removed with source-intelligence. The
current acquisition-side evidence is collector_stats.json, written beside each
run's raw/articles/clusters artifacts.
"""

import json


VALID_ACCESS_TYPES = {"direct_fetch", "rss", "browser", "unknown"}
VALID_STATUSES = {"ok", "empty", "error", "unsupported", "skipped"}


def _write_stats(path, sources):
    path.write_text(json.dumps({
        "domain": "storage",
        "date": "2026-05-30",
        "total_results": sum(src.get("hits", 0) for src in sources),
        "sources": sources,
    }))


def _load(path):
    return json.loads(path.read_text())


class TestCollectorStatsRequired:
    def test_collector_stats_valid_json(self, tmp_path):
        path = tmp_path / "collector_stats.json"
        _write_stats(path, [{
            "source": "micron-newsroom",
            "access": "direct_fetch",
            "status": "ok",
            "hits": 3,
            "duration_ms": 12.5,
            "locale": "en",
            "category": "newsroom",
            "dated": 2,
        }])

        data = _load(path)
        assert data["domain"] == "storage"
        assert isinstance(data["sources"], list)


class TestCollectorStatsFields:
    def test_source_stats_required_fields(self, tmp_path):
        path = tmp_path / "collector_stats.json"
        _write_stats(path, [{
            "source": "servethehome-rss",
            "access": "rss",
            "status": "ok",
            "hits": 5,
            "selected": 4,
            "duration_ms": 20.0,
            "locale": "en",
            "category": "media",
            "dated": 5,
        }])

        required = {"source", "access", "status", "hits", "selected", "duration_ms", "dated"}
        for source in _load(path)["sources"]:
            assert required <= set(source)

    def test_access_type_valid(self, tmp_path):
        path = tmp_path / "collector_stats.json"
        _write_stats(path, [
            {
                "source": f"source-{access}",
                "access": access,
                "status": "ok",
                "hits": 1,
                "selected": 1,
                "duration_ms": 1.0,
                "dated": 1,
            }
            for access in VALID_ACCESS_TYPES
        ])

        for source in _load(path)["sources"]:
            assert source["access"] in VALID_ACCESS_TYPES

    def test_status_valid(self, tmp_path):
        path = tmp_path / "collector_stats.json"
        _write_stats(path, [
            {
                "source": f"source-{status}",
                "access": "direct_fetch",
                "status": status,
                "hits": 0,
                "selected": 0,
                "duration_ms": 1.0,
                "dated": 0,
            }
            for status in VALID_STATUSES
        ])

        for source in _load(path)["sources"]:
            assert source["status"] in VALID_STATUSES

    def test_dated_count_not_greater_than_hits(self, tmp_path):
        path = tmp_path / "collector_stats.json"
        _write_stats(path, [{
            "source": "micron-newsroom",
            "access": "direct_fetch",
            "status": "ok",
            "hits": 3,
            "selected": 2,
            "duration_ms": 12.5,
            "dated": 2,
        }])

        source = _load(path)["sources"][0]
        assert source["dated"] <= source["hits"]

    def test_no_duplicate_source_ids(self, tmp_path):
        path = tmp_path / "collector_stats.json"
        _write_stats(path, [
            {
                "source": f"source-{i}",
                "access": "rss",
                "status": "ok",
                "hits": i,
                "selected": i,
                "duration_ms": 1.0,
                "dated": i,
            }
            for i in range(3)
        ])

        sources = [source["source"] for source in _load(path)["sources"]]
        assert len(sources) == len(set(sources))
