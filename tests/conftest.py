"""Shared pytest fixtures for Stratum tests."""

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest


# ── Paths ──────────────────────────────────────────────────

@pytest.fixture
def fixtures_dir():
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def schemas_dir():
    """Legacy name — redirects to stratum/contracts/."""
    return Path(__file__).resolve().parents[1] / "stratum" / "contracts"


# ── Temporary directories ──────────────────────────────────

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ── Dates ──────────────────────────────────────────────────

@pytest.fixture
def today():
    return date(2025, 6, 15)


@pytest.fixture
def yesterday(today):
    return today - timedelta(days=1)


@pytest.fixture
def week_ago(today):
    return today - timedelta(days=7)


@pytest.fixture
def month_ago(today):
    return today - timedelta(days=30)


# ── Sample JSONL data ──────────────────────────────────────

@pytest.fixture
def valid_articles_jsonl(tmp_dir):
    """Write a valid articles.jsonl and return path."""
    lines = [
        {
            "id": "a001",
            "url": "https://news.skhynix.com/hbm4",
            "canonical_url": "https://news.skhynix.com/hbm4",
            "title": "SK hynix HBM4 Mass Production",
            "source": "SK hynix Newsroom",
            "source_type": "official",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date_source": "url_path",
            "fetched_at": "2025-06-15T11:00:00Z",
            "content_hash": "hash-a001",
            "entities": ["SK hynix"],
            "terms": ["HBM4"],
            "verification_status": "verified",
            "discovery_mode": "collector",
            "query_dimension": "official_sources",
            "artifact_type": "news_article",
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
            "published_at": "2025-06-15T12:00:00Z",
            "date_source": "search_api",
            "fetched_at": "2025-06-15T13:00:00Z",
            "content_hash": "hash-a002",
            "entities": ["Samsung", "NVIDIA"],
            "terms": ["HBM4"],
            "verification_status": "verified",
            "discovery_mode": "baseline_seed",
            "query_dimension": "technology",
            "artifact_type": "news_article",
            "snippet": "HBM4 samples shipped to NVIDIA.",
            "cluster_id": "sc-storage-0001",
        },
        {
            "id": "a003",
            "url": "https://cxmt.com/ddr5",
            "canonical_url": "https://cxmt.com/ddr5",
            "title": "CXMT DDR5 样品发布",
            "source": "CXMT",
            "source_type": "official",
            "source_locale": "zh-CN",
            "published_at": "2025-06-15T08:00:00Z",
            "date_source": "url_path",
            "fetched_at": "2025-06-15T09:00:00Z",
            "content_hash": "hash-a003",
            "entities": ["CXMT"],
            "terms": ["DDR5"],
            "verification_status": "verified",
            "discovery_mode": "collector",
            "query_dimension": "official_sources",
            "artifact_type": "news_article",
            "snippet": "DDR5 样品正式发布。",
        },
    ]
    path = tmp_dir / "articles.jsonl"
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return str(path)


@pytest.fixture
def valid_clusters_json(tmp_dir):
    """Write a valid story-clusters.json and return path."""
    data = {
        "date": "2025-06-15",
        "domain": "storage",
        "total_articles": 3,
        "clustered_articles": 2,
        "clusters": [
            {
                "id": "sc-storage-0001",
                "created": "2025-06-15",
                "canonical_title": "HBM4 Production Milestones",
                "canonical_summary": "Multiple HBM4 production milestones surfaced.",
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
                "entities": ["Samsung", "SK hynix"],
                "terms": ["HBM4"],
            },
        ],
        "unclustered": 1,
    }
    path = tmp_dir / "clusters.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return str(path)
