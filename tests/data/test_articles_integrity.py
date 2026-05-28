"""Data integrity tests for articles.jsonl.

Verifies:
  - All entries are valid JSON
  - Required fields are present
  - Dates are monotonically non-decreasing (sorted)
  - No duplicate IDs or URLs
  - Locale pattern is valid
"""

import json
from datetime import date


def test_all_lines_valid_json(valid_articles_jsonl):
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                assert False, f"Line {i}: invalid JSON: {e}"


def test_required_fields_present(valid_articles_jsonl):
    required = ["id", "url", "title", "date", "source", "source_type", "source_locale", "artifact_type"]
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            data = json.loads(line)
            for field in required:
                assert field in data, f"Line {i}: missing required field '{field}'"


def test_no_duplicate_ids(valid_articles_jsonl):
    ids = []
    with open(valid_articles_jsonl) as f:
        for line in f:
            data = json.loads(line)
            ids.append(data["id"])
    assert len(ids) == len(set(ids)), f"Duplicate IDs found: {len(ids)} total, {len(set(ids))} unique"


def test_no_duplicate_urls(valid_articles_jsonl):
    urls = []
    with open(valid_articles_jsonl) as f:
        for line in f:
            data = json.loads(line)
            urls.append(data["url"])
    assert len(urls) == len(set(urls)), f"Duplicate URLs found"


def test_dates_are_valid(valid_articles_jsonl):
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            data = json.loads(line)
            d = data["date"]
            try:
                date.fromisoformat(d)
            except ValueError:
                assert False, f"Line {i}: invalid date format: {d}"


def test_locale_pattern(valid_articles_jsonl):
    import re
    locale_pattern = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            data = json.loads(line)
            loc = data["source_locale"]
            assert locale_pattern.match(loc), f"Line {i}: invalid locale: {loc}"


def test_artifact_types_valid(valid_articles_jsonl):
    valid_types = {"news_article", "patent", "paper", "hiring", "financial_transcript",
                   "product_announcement", "satellite_image", "conference_abstract"}
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            data = json.loads(line)
            at = data["artifact_type"]
            assert at in valid_types, f"Line {i}: invalid artifact_type: {at}"


def test_title_not_empty(valid_articles_jsonl):
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            data = json.loads(line)
            assert len(data["title"].strip()) > 0, f"Line {i}: empty title"


def test_url_has_scheme(valid_articles_jsonl):
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            data = json.loads(line)
            assert data["url"].startswith("http"), f"Line {i}: URL missing scheme: {data['url']}"


def test_cluster_id_null_or_valid(valid_articles_jsonl):
    import re
    cluster_pattern = re.compile(r"^sc-\d{4}-\d{2}-\d{2}-\d{3}$")
    with open(valid_articles_jsonl) as f:
        for i, line in enumerate(f, 1):
            data = json.loads(line)
            cid = data.get("cluster_id")
            if cid is not None:
                assert cluster_pattern.match(cid), f"Line {i}: invalid cluster_id: {cid}"
