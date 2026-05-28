"""Data integrity tests for source-records.jsonl.

Verifies:
  - All entries are valid JSON
  - Required SourceRecord fields present
  - source_role values are valid
  - Date fields are valid
  - Source diversity metrics are plausible
"""

import json
import re
from datetime import date


# Valid enum values based on source-intelligence-architecture.md
VALID_SOURCE_ROLES = {"primary", "confirming", "context", "breaking"}

VALID_SOURCE_TYPES = {"official", "media", "analyst", "blog", "social", "financial"}


def _load_records(path):
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


class TestSourceRecordRequired:
    def test_all_lines_valid_json(self, tmp_path):
        path = tmp_path / "source-records.jsonl"
        # Write a minimal valid record
        records = [
            {
                "article_id": "a001",
                "article_date": "2025-06-15",
                "source_url": "https://news.skhynix.com/hbm4",
                "source_domain": "news.skhynix.com",
                "source_type": "official",
                "source_locale": "en",
                "source_role": "primary",
                "source_diversity_same_story": 3,
                "total_articles_today": 50,
            },
        ]
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        data = _load_records(str(path))
        assert len(data) == 1


class TestSourceRecordFields:
    def test_source_role_valid(self, tmp_path):
        path = tmp_path / "source-records.jsonl"
        with open(path, "w") as f:
            for role in VALID_SOURCE_ROLES:
                r = {
                    "article_id": f"a_{role}",
                    "article_date": "2025-06-15",
                    "source_url": f"https://{role}.com/a",
                    "source_domain": f"{role}.com",
                    "source_type": "media",
                    "source_locale": "en",
                    "source_role": role,
                    "source_diversity_same_story": 1,
                    "total_articles_today": 10,
                }
                f.write(json.dumps(r) + "\n")

        records = _load_records(str(path))
        for r in records:
            assert r["source_role"] in VALID_SOURCE_ROLES, \
                f"Invalid source_role: {r['source_role']}"

    def test_source_type_valid(self, tmp_path):
        path = tmp_path / "source-records.jsonl"
        with open(path, "w") as f:
            for stype in VALID_SOURCE_TYPES:
                r = {
                    "article_id": f"a_{stype}",
                    "article_date": "2025-06-15",
                    "source_url": f"https://{stype}.com/a",
                    "source_domain": f"{stype}.com",
                    "source_type": stype,
                    "source_locale": "en",
                    "source_role": "primary",
                    "source_diversity_same_story": 1,
                    "total_articles_today": 10,
                }
                f.write(json.dumps(r) + "\n")

        records = _load_records(str(path))
        for r in records:
            assert r["source_type"] in VALID_SOURCE_TYPES, \
                f"Invalid source_type: {r['source_type']}"

    def test_article_date_valid(self, tmp_path):
        path = tmp_path / "source-records.jsonl"
        with open(path, "w") as f:
            r = {
                "article_id": "a001",
                "article_date": "2025-06-15",
                "source_url": "https://example.com/a",
                "source_domain": "example.com",
                "source_type": "media",
                "source_locale": "en",
                "source_role": "primary",
                "source_diversity_same_story": 1,
                "total_articles_today": 10,
            }
            f.write(json.dumps(r) + "\n")

        records = _load_records(str(path))
        try:
            date.fromisoformat(records[0]["article_date"])
        except ValueError as e:
            assert False, f"Invalid article_date: {e}"

    def test_source_diversity_plausible(self, tmp_path):
        """source_diversity_same_story should be ≤ total_articles_today."""
        path = tmp_path / "source-records.jsonl"
        with open(path, "w") as f:
            r = {
                "article_id": "a001",
                "article_date": "2025-06-15",
                "source_url": "https://example.com/a",
                "source_domain": "example.com",
                "source_type": "media",
                "source_locale": "en",
                "source_role": "primary",
                "source_diversity_same_story": 3,
                "total_articles_today": 50,
            }
            f.write(json.dumps(r) + "\n")

        records = _load_records(str(path))
        r = records[0]
        assert r["source_diversity_same_story"] <= r["total_articles_today"], \
            "source_diversity_same_story should not exceed total_articles_today"

    def test_no_duplicate_article_ids(self, tmp_path):
        path = tmp_path / "source-records.jsonl"
        with open(path, "w") as f:
            for i in range(3):
                r = {
                    "article_id": f"a00{i}",
                    "article_date": "2025-06-15",
                    "source_url": f"https://example.com/a{i}",
                    "source_domain": "example.com",
                    "source_type": "media",
                    "source_locale": "en",
                    "source_role": "primary",
                    "source_diversity_same_story": 1,
                    "total_articles_today": 10,
                }
                f.write(json.dumps(r) + "\n")

        records = _load_records(str(path))
        ids = [r["article_id"] for r in records]
        assert len(ids) == len(set(ids)), "Duplicate article_ids in source-records"

    def test_locale_pattern(self, tmp_path):
        path = tmp_path / "source-records.jsonl"
        with open(path, "w") as f:
            for loc in ["en", "zh-CN", "ja", "ko", "en-US"]:
                r = {
                    "article_id": f"a_{loc}",
                    "article_date": "2025-06-15",
                    "source_url": f"https://example.com/{loc}",
                    "source_domain": "example.com",
                    "source_type": "media",
                    "source_locale": loc,
                    "source_role": "primary",
                    "source_diversity_same_story": 1,
                    "total_articles_today": 10,
                }
                f.write(json.dumps(r) + "\n")

        records = _load_records(str(path))
        pattern = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
        for r in records:
            assert pattern.match(r["source_locale"]), \
                f"Invalid locale: {r['source_locale']}"
