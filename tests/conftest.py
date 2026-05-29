"""Shared pytest fixtures for Stratum tests."""

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

# Ensure source-graph-engine is importable
_engine_path = Path(__file__).resolve().parents[1] / "stratum" / "subsystems" / "source-graph"
sys.path.insert(0, str(_engine_path))

from graph import (
    SourceGraph, EntityNode, TermNode, ChannelNode,
    EntityType, TermType, ChannelType, NodeStatus, Edge,
)
from extractor import SearchItem


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


# ── Sample SearchItems ─────────────────────────────────────

@pytest.fixture
def sample_search_items():
    """6 search results covering entities, terms, and channels."""
    return [
        SearchItem(
            title="SK hynix announces HBM4 mass production",
            url="https://news.skhynix.com/hbm4-mass-production",
            snippet="SK hynix has started mass production of HBM4 memory with 1.5TB/s bandwidth.",
            date="2025-06-15",
            engine="tavily",
            source_tier="A",
        ),
        SearchItem(
            title="Samsung ships 36GB HBM4 samples to NVIDIA",
            url="https://semiconductor-today.com/samsung-hbm4-nvidia",
            snippet="Samsung Electronics confirmed shipping 36GB HBM4 samples to NVIDIA Corp.",
            date="2025-06-15",
            engine="tavily",
            source_tier="B",
        ),
        SearchItem(
            title="Samsung HBM4 enters qualification at major customer",
            url="https://www.kedglobal.com/article1",
            snippet="Samsung's HBM4 memory enters final qualification at a major GPU customer.",
            date="2025-06-15",
            engine="tavily",
            source_tier="B",
        ),
        SearchItem(
            title="Micron samples 288-layer 3D NAND",
            url="https://investor.micron.com/news1",
            snippet="Micron Technology announced sampling of 288-layer 3D NAND flash memory.",
            date="2025-06-14",
            engine="tavily",
            source_tier="A",
        ),
        SearchItem(
            title="CXMT 发布 DDR5 样品",
            url="https://cxmt.com/news/ddr5-sampling",
            snippet="长鑫存储正式发布 DDR5 内存样品，采用 12nm 制程。",
            date="2025-06-15",
            engine="tavily",
            source_tier="A",
        ),
        SearchItem(
            title="New blog post on advanced packaging trends",
            url="https://someblog.com/advanced-packaging-2025",
            snippet="A look at advanced packaging trends including CoWoS and hybrid bonding.",
            date="2025-06-15",
            engine="brave",
            source_tier="C",
        ),
    ]


# ── Empty Graph ────────────────────────────────────────────

@pytest.fixture
def empty_graph():
    g = SourceGraph(domain="storage")
    g.initialized = "2025-01-01"
    g.last_evolved = "2025-06-14"
    return g


# ── Seeded Graph ───────────────────────────────────────────

@pytest.fixture
def seeded_graph(empty_graph, week_ago):
    """Graph with SEED entities/terms/channels and one WATCH entity."""
    g = empty_graph
    g.last_evolved = week_ago.isoformat()

    # SEED entities
    g.add_entity(EntityNode(
        id="samsung", type=EntityType.COMPANY,
        aliases={"en": "Samsung Electronics", "zh-CN": "三星电子"},
        first_seen=week_ago.isoformat(), last_seen=week_ago.isoformat(),
        score=1.0, status=NodeStatus.SEED,
    ))
    g.add_entity(EntityNode(
        id="skhynix", type=EntityType.COMPANY,
        aliases={"en": "SK hynix", "zh-CN": "SK海力士"},
        first_seen=week_ago.isoformat(), last_seen=week_ago.isoformat(),
        score=1.0, status=NodeStatus.SEED,
    ))

    # WATCH entity (should upgrade to ACTIVE if observed today)
    g.add_entity(EntityNode(
        id="micron", type=EntityType.COMPANY,
        aliases={"en": "Micron Technology"},
        first_seen=week_ago.isoformat(), last_seen=week_ago.isoformat(),
        score=0.5, status=NodeStatus.WATCH,
    ))

    # SEED terms
    g.add_term(TermNode(
        id="hbm4", type=TermType.TECHNOLOGY,
        aliases={"en": "HBM4"},
        first_seen=week_ago.isoformat(), last_seen=week_ago.isoformat(),
        score=1.0, status=NodeStatus.SEED,
    ))
    g.add_term(TermNode(
        id="ddr5", type=TermType.TECHNOLOGY,
        aliases={"en": "DDR5"},
        first_seen=week_ago.isoformat(), last_seen=week_ago.isoformat(),
        score=1.0, status=NodeStatus.SEED,
    ))

    # SEED channel
    g.add_channel(ChannelNode(
        id="semiconductor_today", type=ChannelType.MEDIA,
        url="https://semiconductor-today.com",
        reliability=0.8, first_seen=week_ago.isoformat(),
        last_seen=week_ago.isoformat(), score=0.8, status=NodeStatus.SEED,
    ))

    return g


# ── Graph save/load ────────────────────────────────────────

@pytest.fixture
def graph_path(tmp_dir):
    return str(tmp_dir / "graph-state.json")


@pytest.fixture
def domain_yaml_path(tmp_dir):
    p = tmp_dir / "domain.yaml"
    p.write_text("companies: []\nterms: []\nchannels: []\n")
    return str(p)


# ── Sample JSONL data ──────────────────────────────────────

@pytest.fixture
def valid_articles_jsonl(tmp_dir):
    """Write a valid articles.jsonl and return path."""
    lines = [
        {
            "id": "a001",
            "url": "https://news.skhynix.com/hbm4",
            "title": "SK hynix HBM4 Mass Production",
            "source": "SK hynix Newsroom",
            "source_type": "official",
            "source_locale": "en",
            "published_at": "2025-06-15T10:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
            "snippet": "Mass production of HBM4 begins.",
        },
        {
            "id": "a002",
            "url": "https://semiconductor-today.com/samsung-hbm4",
            "title": "Samsung ships HBM4 to NVIDIA",
            "source": "Semiconductor Today",
            "source_type": "media",
            "source_locale": "en",
            "published_at": "2025-06-15T12:00:00Z",
            "date": "2025-06-15",
            "artifact_type": "news_article",
            "snippet": "HBM4 samples shipped to NVIDIA.",
            "cluster_id": "sc-2025-06-15-001",
        },
        {
            "id": "a003",
            "url": "https://cxmt.com/ddr5",
            "title": "CXMT DDR5 样品发布",
            "source": "CXMT",
            "source_type": "official",
            "source_locale": "zh-CN",
            "published_at": "2025-06-15T08:00:00Z",
            "date": "2025-06-15",
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
        "sc-2025-06-15-001": {
            "id": "sc-2025-06-15-001",
            "date": "2025-06-15",
            "title": "HBM4 Production Milestones",
            "article_ids": ["a001", "a002"],
            "novelty": "update",
            "confidence": "A",
            "source_diversity": "high",
            "linked_entities": ["samsung", "skhynix"],
            "linked_terms": ["hbm4"],
        },
    }
    path = tmp_dir / "story-clusters.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return str(path)
