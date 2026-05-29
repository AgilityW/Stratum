"""Unit tests for the search subsystem.

Covers all pure-function components:
- models: SearchResult parsing, domain extraction, source classification, scoring
- curator: freshness scoring, entity scoring, pruning logic
- config: domain.yaml search: section loading
- engine: engine creation, factory

Does NOT cover executor (requires live API keys) — use integration tests for that.
"""

import os
import sys
import tempfile

WORKSPACE = os.path.expanduser("~/ProjectSpace/Stratum")
sys.path.insert(0, WORKSPACE)


# ============================================================
# MODELS
# ============================================================

def test_result_from_bocha():
    from stratum.subsystems.search.models import SearchResult

    raw = {
        "url": "https://example.com/article",
        "name": "Samsung announces HBM4",
        "snippet": "Samsung announced its latest HBM4 memory.",
        "datePublished": "2026-05-29T10:00:00Z",
    }
    r = SearchResult.from_bocha(raw, "zh-CN", "q-001")
    assert r.url == "https://example.com/article"
    assert r.title == "Samsung announces HBM4"
    assert r.locale == "zh-CN"
    assert r.engine == "bocha"
    assert r.query_id == "q-001"
    assert r.published_at == "2026-05-29T10:00:00Z"
    print("  ✓ SearchResult.from_bocha")


def test_result_from_tavily():
    from stratum.subsystems.search.models import SearchResult

    raw = {
        "url": "https://nikkei.com/article/123",
        "title": "キオクシア、新NAND発表",
        "content": "キオクシアが次世代NANDを発表した。",
        "published_date": None,
    }
    r = SearchResult.from_tavily(raw, "ja", "q-050")
    assert r.url == "https://nikkei.com/article/123"
    assert r.locale == "ja"
    assert r.engine == "tavily"
    assert r.published_at is None
    print("  ✓ SearchResult.from_tavily")


def test_result_with_domain():
    from stratum.subsystems.search.models import SearchResult

    r = SearchResult(url="https://www.nikkei.com/article/123", title="Test", snippet="",
                     locale="ja", engine="tavily", query_id="q-001")
    r.with_domain()
    assert r.source_domain == "nikkei.com"
    print("  ✓ SearchResult.with_domain")


def test_result_with_source_hint():
    from stratum.subsystems.search.models import SearchResult

    classifications = {
        "official": ["samsung.com/semiconductor"],
        "analyst": ["trendforce.com"],
        "media": ["reuters.com", "nikkei.com"],
    }
    r = SearchResult(url="https://www.trendforce.com/press", title="Test", snippet="",
                     locale="en", engine="tavily", query_id="q-001")
    r.with_source_hint(classifications)
    assert r.source_type_hint == "analyst"

    r2 = SearchResult(url="https://reuters.com/article", title="Test", snippet="",
                      locale="en", engine="tavily", query_id="q-002")
    r2.with_source_hint(classifications)
    assert r2.source_type_hint == "media"

    r3 = SearchResult(url="https://unknown-blog.com/post", title="Test", snippet="",
                      locale="en", engine="tavily", query_id="q-003")
    r3.with_source_hint(classifications)
    assert r3.source_type_hint == "media"  # default
    print("  ✓ SearchResult.with_source_hint")


def test_query_substitution():
    from stratum.subsystems.search.models import Query

    q = Query(id="q-001", text="memory chip ${CURRENT_YEAR}", locale="en")
    sub = q.with_substitutions("2026-05-29")
    assert "2026" in sub.text
    assert "${CURRENT_YEAR}" not in sub.text
    print("  ✓ Query.with_substitutions")


def test_result_set_stats():
    from stratum.subsystems.search.models import ResultSet, SearchResult

    rs = ResultSet(
        results=[
            SearchResult(url="https://a.com", title="A", snippet="", locale="en",
                         engine="tavily", query_id="q1", source_type_hint="media"),
            SearchResult(url="https://b.com", title="B", snippet="", locale="ja",
                         engine="tavily", query_id="q2", source_type_hint="analyst"),
            SearchResult(url="https://c.com", title="C", snippet="", locale="en",
                         engine="bocha", query_id="q3", source_type_hint="media"),
        ],
        date="2026-05-29", total_raw=10, total_curated=3,
    )
    stats = rs.to_stats_json()
    assert stats["total_raw"] == 10
    assert stats["total_curated"] == 3
    assert stats["by_engine"]["tavily"] == 2
    assert stats["by_engine"]["bocha"] == 1
    assert stats["by_locale"]["en"] == 2
    assert stats["by_locale"]["ja"] == 1
    print("  ✓ ResultSet.to_stats_json")


# ============================================================
# CURATOR
# ============================================================

def test_freshness_score():
    from stratum.subsystems.search.curator import _freshness_score

    assert _freshness_score("2026-05-29T10:00:00", "2026-05-29") == 1.0
    assert _freshness_score("2026-05-28", "2026-05-29") == 0.7
    assert _freshness_score("2026-05-20", "2026-05-29") == 0.3
    assert _freshness_score(None, "2026-05-29") == 0.3
    assert _freshness_score("bad-date", "2026-05-29") == 0.3
    print("  ✓ _freshness_score")


def test_entity_score():
    from stratum.subsystems.search.curator import _entity_score

    entities = [
        {"id": "samsung", "name_en": "Samsung", "name_zh": "三星"},
        {"id": "sk-hynix", "name_en": "SK hynix", "name_zh": "SK海力士"},
    ]
    terms = [
        {"name_en": "HBM4"},
        {"name_en": "NAND"},
    ]
    # High match
    s1 = _entity_score("Samsung HBM4 launch", "Samsung announces HBM4 and NAND", entities, terms)
    assert s1 > 0.4  # 3+ hits

    # Zero match
    s2 = _entity_score("Random news", "nothing relevant here", entities, terms)
    assert s2 == 0.0
    print("  ✓ _entity_score")


def test_score_and_sort():
    from stratum.subsystems.search.models import SearchResult
    from stratum.subsystems.search.curator import score

    entities = [{"id": "samsung", "name_en": "Samsung", "name_zh": ""}]
    terms = [{"name_en": "HBM4"}]
    source_weights = {"official": 1.0, "media": 0.6}

    # High-quality: official source, today, lots of entities
    r1 = SearchResult(url="https://a.com", title="Samsung HBM4 launch", snippet="HBM4 production",
                      locale="en", published_at="2026-05-29", source_type_hint="official", engine="tavily", query_id="q1")
    # Low-quality: blog, old, no entities
    r2 = SearchResult(url="https://b.com", title="Random post", snippet="nothing",
                      locale="en", published_at="2026-05-20", source_type_hint="blog", engine="tavily", query_id="q2")

    results = score([r2, r1], "2026-05-29", source_weights, entities, terms)
    # Higher score should be first
    assert results[0].score > results[1].score
    assert results[0].title == "Samsung HBM4 launch"
    print("  ✓ score + sort")


def test_prune_limits():
    from stratum.subsystems.search.models import SearchResult
    from stratum.subsystems.search.curator import prune

    results = [
        SearchResult(url=f"https://source-a.com/{i}", title=f"A{i}", snippet="",
                     locale="en", source_domain="source-a.com", engine="t", query_id="q", score=0.9 - i * 0.01)
        for i in range(10)
    ] + [
        SearchResult(url=f"https://source-b.com/{i}", title=f"B{i}", snippet="",
                     locale="ja", source_domain="source-b.com", engine="t", query_id="q", score=0.8 - i * 0.01)
        for i in range(5)
    ]

    pruned = prune(results, max_per_locale=5, max_per_source=3, total_cap=8)
    # 3 from source-a (per-source=3 hits before per-locale=5) + 3 from source-b = 6
    assert len(pruned) == 6
    # source-a: max 3
    a_count = sum(1 for r in pruned if r.source_domain == "source-a.com")
    assert a_count == 3
    # source-b: max 3
    b_count = sum(1 for r in pruned if r.source_domain == "source-b.com")
    assert b_count == 3
    print("  ✓ prune limits")


# ============================================================
# CONFIG
# ============================================================

def test_load_search_config():
    """search: section in domain.yaml loads with all keys."""
    from stratum.subsystems.search.config import load_search_config

    config = load_search_config("storage", WORKSPACE)
    assert "routing" in config
    assert "engines" in config
    assert "source_weights" in config
    assert "classifications" in config
    assert "entities" in config
    assert "terms" in config

    # Routing — from config.yaml engines.{name}.languages
    assert config["routing"]["zh-CN"] == ["bocha", "tavily"]  # bocha primary + tavily fallback
    assert config["routing"]["ja"] == ["tavily"]
    assert config["routing"]["en"] == ["tavily"]

    # Engines
    assert "bocha" in config["engines"]
    assert "tavily" in config["engines"]

    # Curation
    assert config["source_weights"]["official"] == 1.0
    assert config["max_per_locale"] == 30
    assert config["total_cap"] == 200

    print("  ✓ load_search_config")


# ============================================================
# ENGINE
# ============================================================

def test_create_engines():
    """Engine factory creates correct instances."""
    from stratum.subsystems.search.engine import create_engines, BochaEngine, TavilyEngine

    engine_configs = {
        "bocha": {"freshness": "oneDay", "count": 10},
        "tavily": {"search_depth": "advanced", "max_results": 10, "include_domains": {"ja": ["nikkei.com"]}},
    }
    api_keys = {"bocha": "fake-bocha-key", "tavily": "fake-tavily-key"}

    engines = create_engines(engine_configs, api_keys)
    assert "bocha" in engines
    assert "tavily" in engines
    assert isinstance(engines["bocha"], BochaEngine)
    assert isinstance(engines["tavily"], TavilyEngine)
    assert engines["bocha"].api_key == "fake-bocha-key"
    assert engines["tavily"].include_domains == {"ja": ["nikkei.com"]}

    # With no configs
    engines2 = create_engines({}, {})
    assert len(engines2) == 0

    print("  ✓ create_engines")


# ============================================================
# RUNNER
# ============================================================

if __name__ == "__main__":
    print("Search Subsystem Unit Tests")
    print("=" * 50)

    tests = [
        # models
        test_result_from_bocha,
        test_result_from_tavily,
        test_result_with_domain,
        test_result_with_source_hint,
        test_query_substitution,
        test_result_set_stats,
        # curator
        test_freshness_score,
        test_entity_score,
        test_score_and_sort,
        test_prune_limits,
        # config
        test_load_search_config,
        # engine
        test_create_engines,
    ]

    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  ✗ {t.__name__}: {e}")
            traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{len(tests)} passed")
    if passed == len(tests):
        print("✅ All search subsystem tests passed")
    else:
        print(f"❌ {len(tests) - passed} test(s) failed")
        sys.exit(1)
