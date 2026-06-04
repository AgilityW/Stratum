"""Unit tests for the discovery subsystem.

Covers all pure-function components:
- models: SearchResult parsing, domain extraction, source classification, scoring
- curator: freshness scoring, entity scoring, pruning logic
- config: domain.yaml search: section loading
- engine: engine creation, factory

Does NOT cover executor (requires live API keys) — use integration tests for that.
"""

import os
import sqlite3
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ============================================================
# MODELS
# ============================================================

def test_result_from_bocha():
    from stratum.sourcing.discovery import SearchResult

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


def test_discovery_package_exports_stable_surface():
    import stratum.sourcing.discovery as discovery

    assert "run_search" in discovery.__all__
    assert "load_search_config" in discovery.__all__
    assert "load_api_keys" in discovery.__all__
    assert "build_diagnostics" in discovery.__all__
    assert "Query" in discovery.__all__
    assert "ResultSet" in discovery.__all__


def test_acquisition_package_exports_stable_surface():
    import stratum.stages.acquisition as acquisition

    assert "load_queries_flat" in acquisition.__all__
    assert "load_queries_from_db" in acquisition.__all__
    assert "resolve_queries" in acquisition.__all__
    assert "merge_raw_results" in acquisition.__all__
    assert "discovery_candidate_rows" in acquisition.__all__
    assert "skipped_query_stats" in acquisition.__all__


def test_search_package_exports_compatibility_surface():
    import stratum.stages.search as search

    assert "load_queries_flat" in search.__all__
    assert "load_queries_from_db" in search.__all__
    assert "resolve_queries" in search.__all__
    assert "merge_raw_results" in search.__all__
    assert "discovery_candidate_rows" in search.__all__
    assert "skipped_query_stats" in search.__all__
    assert "split_queries_by_coverage" in search.__all__


def test_result_from_tavily():
    from stratum.sourcing.discovery import SearchResult

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
    from stratum.sourcing.discovery import SearchResult

    r = SearchResult(url="https://www.nikkei.com/article/123?utm_source=x#top", title="Test", snippet="",
                     locale="ja", engine="tavily", query_id="q-001")
    r.with_domain()
    assert r.source_domain == "nikkei.com"
    assert r.canonical_url == "https://nikkei.com/article/123"
    print("  ✓ SearchResult.with_domain")


def test_canonicalize_url_normalizes_tracking_and_mobile_hosts():
    from stratum.sourcing.discovery import canonicalize_url

    assert canonicalize_url(
        "HTTPS://www.example.com/path/?utm_source=news&b=2&a=1#frag"
    ) == "https://example.com/path?a=1&b=2"
    assert canonicalize_url("https://m.example.com/path/") == "https://example.com/path"


def test_result_with_source_hint():
    from stratum.sourcing.discovery import SearchResult

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


def test_source_hint_respects_domain_boundaries():
    from stratum.sourcing.discovery import SearchResult, source_pattern_matches

    classifications = {
        "official": ["samsung.com/semiconductor"],
        "analyst": ["reuters.com"],
    }

    assert source_pattern_matches("https://asia.reuters.com/technology", "reuters.com")
    assert not source_pattern_matches("https://notreuters.com/technology", "reuters.com")

    official = SearchResult(
        url="https://semiconductor.samsung.com/newsroom/update",
        title="Samsung update",
        snippet="",
        locale="en",
        engine="tavily",
        query_id="q1",
    )
    official.with_source_hint(classifications)
    assert official.source_type_hint == "official"

    imposter = SearchResult(
        url="https://notreuters.com/technology",
        title="Reuters-looking source",
        snippet="",
        locale="en",
        engine="tavily",
        query_id="q2",
    )
    imposter.with_source_hint(classifications)
    assert imposter.source_type_hint == "media"


def test_query_substitution():
    from stratum.sourcing.discovery import Query

    q = Query(id="q-001", text="memory chip ${CURRENT_YEAR}", locale="en")
    sub = q.with_substitutions("2026-05-29")
    assert "2026" in sub.text
    assert "${CURRENT_YEAR}" not in sub.text
    print("  ✓ Query.with_substitutions")


def test_normalize_include_domains_accepts_urls_and_dedupes():
    from stratum.sourcing.discovery import normalize_include_domains

    assert normalize_include_domains([
        "https://www.Semiconductor.Samsung.com/newsroom/",
        "m.reuters.com",
        "reuters.com",
    ]) == ["semiconductor.samsung.com", "reuters.com"]


def test_normalize_include_domains_rejects_invalid_shape():
    from stratum.sourcing.discovery import normalize_include_domains
    import pytest

    with pytest.raises(ValueError, match="include_domains"):
        normalize_include_domains({"en": ["reuters.com"]})


def test_result_set_stats():
    from stratum.sourcing.discovery import ResultSet, SearchResult

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
    assert stats["diagnostics"] == {}
    assert stats["queries"][0]["dimension"] == "general"
    print("  ✓ ResultSet.to_stats_json")


def test_result_set_raw_json_prefers_full_raw_results():
    from stratum.sourcing.discovery import ResultSet, SearchResult

    curated = SearchResult(
        url="https://a.com",
        title="Curated",
        snippet="",
        locale="en",
        engine="tavily",
        query_id="q1",
    )
    raw = [
        curated,
        SearchResult(
            url="https://b.com",
            title="Raw only",
            snippet="",
            locale="en",
            engine="bocha",
            query_id="q2",
        ),
    ]

    rs = ResultSet(
        results=[curated],
        raw_results=raw,
        date="2026-05-30",
        total_raw=2,
        total_curated=1,
    )

    payload = rs.to_raw_json()
    assert [item["url"] for item in payload] == ["https://a.com", "https://b.com"]


def test_split_queries_by_coverage_skips_covered_domain_queries():
    from stratum.stages.search import split_queries_by_coverage

    existing_raw = [
        {"url": "https://www.reuters.com/technology/article", "source_domain": "reuters.com"},
        {"url": "https://semiconductor.samsung.com/newsroom/post"},
    ]
    queries = [
        {
            "id": "q-covered",
            "text": "Reuters memory chip news",
            "locale": "en",
            "include_domains": ["www.reuters.com"],
        },
        {
            "id": "q-subdomain",
            "text": "Samsung semiconductor news",
            "locale": "en",
            "include_domains": ["semiconductor.samsung.com"],
        },
        {
            "id": "q-uncovered",
            "text": "Micron news",
            "locale": "en",
            "include_domains": ["micron.com"],
        },
        {"id": "q-broad", "text": "HBM market news", "locale": "en"},
    ]

    active, skipped = split_queries_by_coverage(queries, existing_raw)

    assert [q["id"] for q in skipped] == ["q-covered", "q-subdomain"]
    assert [q["id"] for q in active] == ["q-uncovered", "q-broad"]


def test_query_planner_explains_covered_query_decision():
    from stratum.sourcing.discovery.query_planner import QueryPlanner

    planner = QueryPlanner([
        {"url": "https://news.samsung.com/article", "source_domain": "news.samsung.com"}
    ])

    decision = planner.coverage_decision({
        "id": "q-samsung",
        "include_domains": ["samsung.com"],
    })

    assert decision.query_id == "q-samsung"
    assert decision.skipped is True
    assert decision.reason == "covered_by_higher_priority_raw"


def test_search_supplement_policy_skips_and_explains_covered_queries():
    from stratum.sourcing.discovery.query_planner import SearchSupplementPolicy

    policy = SearchSupplementPolicy([
        {"url": "https://news.samsung.com/article", "source_domain": "news.samsung.com"}
    ])
    queries = [
        {"id": "q-samsung", "text": "Samsung news", "locale": "en", "include_domains": ["samsung.com"]},
        {"id": "q-micron", "text": "Micron news", "locale": "en", "include_domains": ["micron.com"]},
    ]

    active, skipped = policy.prepare_queries(queries, skip_covered_domain_queries=True)
    stats = policy.skipped_query_stats(skipped)

    assert [query["id"] for query in active] == ["q-micron"]
    assert [query["id"] for query in skipped] == ["q-samsung"]
    assert stats[0]["status"] == "skipped_covered"
    assert stats[0]["engine_used"] == "collector"
    assert stats[0]["include_domains"] == ["samsung.com"]


def test_search_supplement_policy_keeps_existing_raw_before_search_supplement():
    from stratum.sourcing.discovery.query_planner import SearchSupplementPolicy

    policy = SearchSupplementPolicy([
        {"url": "https://www.example.com/a?utm_source=x", "title": "collector"}
    ])

    merged = policy.merge_results([
        {"url": "https://example.com/a", "title": "duplicate search"},
        {"url": "https://example.com/b", "title": "search supplement"},
    ])

    assert [item["title"] for item in merged] == ["collector", "search supplement"]
    assert merged[0]["canonical_url"] == "https://example.com/a"


def test_search_supplement_policy_builds_zero_query_stats_payload():
    from stratum.sourcing.discovery.query_planner import SearchSupplementPolicy

    policy = SearchSupplementPolicy([{"url": "https://example.com/a", "title": "collector"}])
    payload = policy.zero_query_stats_payload(
        run_date="2026-05-30",
        merged_results=policy.merge_results([]),
        skipped_queries=[{"id": "q-covered", "locale": "en", "include_domains": ["example.com"]}],
    )

    assert payload["date"] == "2026-05-30"
    assert payload["total_raw"] == 1
    assert payload["diagnostics"] == {
        "existing_raw": 1,
        "search_raw": 0,
        "skipped_covered_queries": 1,
    }
    assert payload["queries"][0]["query_id"] == "q-covered"


def test_query_performance_scorer_recommends_low_yield_actions():
    from stratum.sourcing.discovery.query_planner import QueryPerformanceScorer

    scorer = QueryPerformanceScorer(min_attempts=3, low_yield_rate=0.5)
    diagnostics = scorer.diagnostics([
        {"query_id": "q-good", "status": "success", "results_count": 3},
        {"query_id": "q-good", "status": "fallback", "results_count": 2},
        {"query_id": "q-good", "status": "success", "results_count": 1},
        {"query_id": "q-empty", "status": "no_results", "results_count": 0},
        {"query_id": "q-empty", "status": "no_results", "results_count": 0},
        {"query_id": "q-empty", "status": "no_results", "results_count": 0},
        {"query_id": "q-failed", "status": "failed", "results_count": 0},
        {"query_id": "q-failed", "status": "rate_limited", "results_count": 0},
        {"query_id": "q-failed", "status": "failed", "results_count": 0},
        {"query_id": "q-thin", "status": "success", "results_count": 0},
        {"query_id": "q-thin", "status": "success", "results_count": 0},
        {"query_id": "q-thin", "status": "success", "results_count": 1},
    ])

    records = {record["query_id"]: record for record in diagnostics["records"]}

    assert records["q-good"]["recommendation"] == "keep"
    assert records["q-empty"]["recommendation"] == "expand_or_replace"
    assert records["q-failed"]["recommendation"] == "expand_or_replace"
    assert records["q-thin"]["recommendation"] == "retire_or_rewrite"
    assert records["q-empty"]["rewrite_hint"] == "broaden_terms_or_add_alternate_source_domains"
    assert records["q-failed"]["rewrite_hint"] == "check_engine_route_or_replace_source_filters"
    assert records["q-thin"]["rewrite_hint"] == "rewrite_query_or_retire_after_review"
    assert [record["query_id"] for record in diagnostics["gap_expansion_candidates"]] == [
        "q-empty",
        "q-failed",
    ]
    assert [record["query_id"] for record in diagnostics["low_yield_retirement_candidates"]] == ["q-thin"]


def test_query_planner_orders_and_optionally_retires_by_performance():
    from stratum.sourcing.discovery.query_planner import QueryPlanner

    queries = [
        {"id": "q-thin", "text": "thin", "locale": "en"},
        {"id": "q-good", "text": "good", "locale": "en"},
        {"id": "q-gap", "text": "gap", "locale": "en"},
    ]
    performance = [
        {"query_id": "q-thin", "recommendation": "retire_or_rewrite", "yield_rate": 0.1, "reason": "low_historical_yield"},
        {"query_id": "q-good", "recommendation": "keep", "yield_rate": 2.0, "reason": "healthy_yield"},
        {"query_id": "q-gap", "recommendation": "expand_or_replace", "yield_rate": 0.0, "reason": "all_attempts_no_results"},
    ]

    active, retired, decisions = QueryPlanner().apply_performance(queries, performance)

    assert [query["id"] for query in active] == ["q-good", "q-gap", "q-thin"]
    assert retired == []
    assert {decision.query_id: decision.action for decision in decisions} == {
        "q-thin": "defer",
        "q-good": "run",
        "q-gap": "defer",
    }

    active, retired, decisions = QueryPlanner().apply_performance(
        queries,
        performance,
        retire_low_yield=True,
    )

    assert [query["id"] for query in active] == ["q-good", "q-gap"]
    assert [query["id"] for query in retired] == ["q-thin"]
    assert next(decision for decision in decisions if decision.query_id == "q-thin").action == "retire"


def test_merge_raw_results_keeps_primary_on_canonical_conflict():
    from stratum.stages.acquisition import merge_raw_results

    primary = [{"url": "https://www.example.com/a?utm_source=x", "title": "primary"}]
    secondary = [
        {"url": "https://example.com/a", "title": "duplicate"},
        {"url": "https://example.com/b", "title": "secondary"},
    ]

    merged = merge_raw_results(primary, secondary)

    assert [item["title"] for item in merged] == ["primary", "secondary"]


# ============================================================
# CURATOR
# ============================================================

def test_freshness_score():
    from stratum.sourcing.discovery.curator import _freshness_score

    assert _freshness_score("2026-05-29T10:00:00", "2026-05-29") == 1.0
    assert _freshness_score("2026-05-28", "2026-05-29") == 0.7
    assert _freshness_score("2026-05-20", "2026-05-29") == 0.3
    assert _freshness_score(None, "2026-05-29") == 0.3
    assert _freshness_score("bad-date", "2026-05-29") == 0.3
    print("  ✓ _freshness_score")


def test_entity_score():
    from stratum.sourcing.discovery.curator import _entity_score

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


def test_entity_score_uses_multilingual_aliases():
    from stratum.sourcing.discovery.curator import _entity_score

    entities = [
        {
            "id": "sk-hynix",
            "name_en": "SK hynix",
            "name_zh": "SK海力士",
            "aliases": ["SK하이닉스", "SKハイニックス"],
        }
    ]
    terms = [
        {
            "id": "advanced-packaging",
            "name_en": "Advanced Packaging",
            "aliases": ["先进封装", "先進封裝"],
        }
    ]

    score = _entity_score("SK하이닉스 HBM update", "先进封装 capacity", entities, terms)

    assert score == 0.4


def test_score_and_sort():
    from stratum.sourcing.discovery import SearchResult
    from stratum.sourcing.discovery.curator import score
    from stratum.sourcing.discovery.curation_policy import SearchResultScorer

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
    direct_results = SearchResultScorer().score_results(
        [r2, r1],
        "2026-05-29",
        source_weights,
        entities,
        terms,
    )
    # Higher score should be first
    assert results[0].score > results[1].score
    assert results[0].title == "Samsung HBM4 launch"
    assert direct_results[0].title == results[0].title
    print("  ✓ score + sort")


def test_search_result_scorer_penalizes_duplicate_title_novelty():
    from stratum.sourcing.discovery.curation_policy import (
        SearchResultScorer,
        batch_source_counts,
        batch_title_counts,
    )
    from stratum.sourcing.discovery import SearchResult

    scorer = SearchResultScorer()
    results = [
        SearchResult(
            url=f"https://wire-{index}.example.com/story",
            title="Samsung HBM4 qualification update",
            snippet="Samsung HBM4",
            locale="en",
            published_at="2026-05-29",
            source_domain=f"wire-{index}.example.com",
            source_type_hint="media",
        )
        for index in range(3)
    ]
    results.append(SearchResult(
        url="https://official.example.com/unique",
        title="Samsung details HBM4 customer qualification milestone",
        snippet="Samsung HBM4",
        locale="en",
        published_at="2026-05-29",
        source_domain="official.example.com",
        source_type_hint="media",
    ))

    ranked = scorer.score_results(
        results,
        "2026-05-29",
        {"media": 0.6},
        [{"id": "samsung", "name_en": "Samsung"}],
        [{"id": "hbm4", "name_en": "HBM4"}],
    )

    title_counts = batch_title_counts(results)
    source_counts = batch_source_counts(results)
    duplicate = next(result for result in ranked if result.title == "Samsung HBM4 qualification update")
    unique = next(result for result in ranked if result.title.startswith("Samsung details"))
    assert scorer.novelty_score(duplicate, title_counts, source_counts) == 0.2
    assert scorer.novelty_score(unique, title_counts, source_counts) == 1.0
    assert ranked[0].title == "Samsung details HBM4 customer qualification milestone"
    assert ranked[0].score > ranked[-1].score


def test_search_result_scorer_uses_source_quality_score():
    from stratum.sourcing.discovery.curation_policy import SearchResultScorer
    from stratum.sourcing.discovery import SearchResult

    scorer = SearchResultScorer()
    official = SearchResult(
        url="https://official.example.com/story",
        title="HBM4 update",
        snippet="",
        locale="en",
        source_type_hint="official",
    )
    blog = SearchResult(
        url="https://blog.example.com/story",
        title="HBM4 update",
        snippet="",
        locale="en",
        source_type_hint="blog",
    )

    assert scorer.source_quality_score(official, {"official": 1.0, "blog": 0.2}) == 1.0
    assert scorer.source_quality_score(blog, {"official": 1.0, "blog": 0.2}) == 0.2


def test_prune_limits():
    from stratum.sourcing.discovery import SearchResult
    from stratum.sourcing.discovery.curator import prune
    from stratum.sourcing.discovery.curation_policy import SearchDiversityRanker

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
    direct_pruned = SearchDiversityRanker().rank(results, max_per_locale=5, max_per_source=3, total_cap=8)
    # 3 from source-a (per-source=3 hits before per-locale=5) + 3 from source-b = 6
    assert len(pruned) == 6
    assert [r.url for r in direct_pruned] == [r.url for r in pruned]
    # source-a: max 3
    a_count = sum(1 for r in pruned if r.source_domain == "source-a.com")
    assert a_count == 3
    # source-b: max 3
    b_count = sum(1 for r in pruned if r.source_domain == "source-b.com")
    assert b_count == 3
    print("  ✓ prune limits")


def test_prune_dedupes_by_canonical_url():
    from stratum.sourcing.discovery import SearchResult
    from stratum.sourcing.discovery.curator import curate

    results = [
        SearchResult(
            url="https://www.example.com/story?utm_source=news",
            title="Samsung HBM4",
            snippet="Samsung HBM4",
            locale="en",
            engine="tavily",
            query_id="q1",
        ),
        SearchResult(
            url="https://m.example.com/story/",
            title="Samsung HBM4 duplicate",
            snippet="Samsung HBM4",
            locale="en",
            engine="bocha",
            query_id="q2",
        ),
    ]

    curated = curate(
        results,
        run_date="2026-05-30",
        source_weights={"media": 0.6},
        classifications={"media": ["example.com"]},
        entities=[{"id": "samsung", "name_en": "Samsung", "name_zh": "三星"}],
        terms=[],
        max_per_locale=10,
        max_per_source=10,
        total_cap=10,
    )

    assert len(curated) == 1
    assert curated[0].canonical_url == "https://example.com/story"


def test_prune_reserves_configured_source_type_mix():
    from stratum.sourcing.discovery import SearchResult
    from stratum.sourcing.discovery.curator import prune

    media_results = [
        SearchResult(
            url=f"https://media-{i}.com/story",
            title=f"Media {i}",
            snippet="",
            locale="en",
            source_domain=f"media-{i}.com",
            source_type_hint="media",
            engine="t",
            query_id="q",
            score=0.95 - i * 0.01,
        )
        for i in range(8)
    ]
    analyst = SearchResult(
        url="https://trendforce.com/report",
        title="Analyst report",
        snippet="",
        locale="en",
        source_domain="trendforce.com",
        source_type_hint="analyst",
        engine="t",
        query_id="q",
        score=0.4,
    )

    pruned = prune(
        media_results + [analyst],
        max_per_locale=10,
        max_per_source=3,
        total_cap=5,
        min_per_source_type={"analyst": 1},
    )

    assert len(pruned) == 5
    assert any(r.source_type_hint == "analyst" for r in pruned)
    assert sum(1 for r in pruned if r.source_type_hint == "media") == 4


def test_prune_limits_single_entity_dominance():
    from stratum.sourcing.discovery import SearchResult
    from stratum.sourcing.discovery.curator import prune

    samsung_results = [
        SearchResult(
            url=f"https://samsung-{i}.com/story",
            title=f"Samsung HBM4 update {i}",
            snippet="Samsung memory roadmap",
            locale="en",
            source_domain=f"samsung-{i}.com",
            source_type_hint="media",
            engine="t",
            query_id="q",
            score=0.95 - i * 0.01,
        )
        for i in range(5)
    ]
    micron_results = [
        SearchResult(
            url=f"https://micron-{i}.com/story",
            title=f"Micron HBM update {i}",
            snippet="Micron memory roadmap",
            locale="en",
            source_domain=f"micron-{i}.com",
            source_type_hint="media",
            engine="t",
            query_id="q",
            score=0.75 - i * 0.01,
        )
        for i in range(3)
    ]

    pruned = prune(
        samsung_results + micron_results,
        max_per_locale=10,
        max_per_source=3,
        total_cap=5,
        entities=[
            {"id": "samsung", "name_en": "Samsung", "name_zh": "三星"},
            {"id": "micron", "name_en": "Micron", "name_zh": "美光"},
        ],
        max_per_entity=2,
    )

    assert len(pruned) == 4
    assert sum(1 for r in pruned if "Samsung" in r.title) == 2
    assert sum(1 for r in pruned if "Micron" in r.title) == 2


# ============================================================
# CONFIG
# ============================================================

def test_load_search_config():
    """search: section in domain.yaml loads with all keys."""
    from stratum.sourcing.discovery.config import load_search_config

    config = load_search_config("storage", str(PROJECT_ROOT))
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
    assert config["engines"]["tavily"]["topic_by_intent"]["verification"] == "general"
    assert config["engines"]["tavily"]["topic_by_dimension"]["financial"] == "general"

    # Curation
    assert config["source_weights"]["official"] == 1.0
    assert config["max_per_locale"] == 30
    assert config["total_cap"] == 200
    assert config["min_per_source_type"] == {"official": 10, "analyst": 10, "media": 10}
    assert config["max_per_entity"] == 40
    assert "company" not in config["classifications"]
    assert "trendforce.com" in config["classifications"]["analyst"]
    assert "samsung.com" in config["classifications"]["official"]
    sk_hynix = next(entity for entity in config["entities"] if entity["id"] == "sk-hynix")
    assert "SK하이닉스" in sk_hynix["aliases"]
    assert "SKハイニックス" in sk_hynix["aliases"]
    advanced_packaging = next(term for term in config["terms"] if term["id"] == "advanced-packaging")
    assert "先进封装" in advanced_packaging["aliases"]

    print("  ✓ load_search_config")


def test_load_search_config_keeps_company_aliases_out_of_source_types():
    """Company aliases must not shadow source-type classification."""
    from stratum.sourcing.discovery.config import load_search_config
    from stratum.sourcing.discovery import SearchResult

    config = load_search_config("storage", str(PROJECT_ROOT))

    result = SearchResult(
        url="https://news.samsung.com/global/samsung-memory-update",
        title="Samsung memory update",
        snippet="",
        locale="en",
        engine="tavily",
        query_id="q1",
    )
    result.with_source_hint(config["classifications"])

    assert result.source_type_hint == "official"


def test_search_wrapper_exposes_narrow_acquisition_surface():
    from stratum.stages.search import search
    from stratum.stages.acquisition import acquisition

    assert search.load_queries_flat is acquisition.load_queries_flat
    assert search.load_queries_from_db is acquisition.load_queries_from_db
    assert search.resolve_queries is acquisition.resolve_queries
    assert search.merge_raw_results is acquisition.merge_raw_results
    assert search.discovery_candidate_rows is acquisition.discovery_candidate_rows
    assert search.split_queries_by_coverage is acquisition.split_queries_by_coverage


def test_load_search_config_honors_explicit_config_path(tmp_path):
    """Stage 1 must use the CLI --config file, not only workspace/config.yaml."""
    from stratum.sourcing.discovery.config import load_search_config

    domain_dir = tmp_path / "domains" / "demo"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
companies:
  - id: demo-company
    aliases: {en: Demo Company}
terms: []
pipeline:
  source_classification: {}
""")
    (tmp_path / "config.yaml").write_text("""
source_languages: [en]
engines:
  tavily:
    languages: [en]
curation:
  total_cap: 11
  max_per_locale: 3
  max_per_source: 1
""")
    alt_config = tmp_path / "alt-search.yaml"
    alt_config.write_text("""
source_languages: [ja]
engines:
  tavily:
    languages: [ja]
curation:
  total_cap: 77
  max_per_locale: 9
  max_per_source: 4
""")

    config = load_search_config("demo", str(tmp_path), config_path=str(alt_config))

    assert "en" not in config["routing"]
    assert config["routing"]["ja"] == ["tavily"]
    assert config["total_cap"] == 77
    assert config["max_per_locale"] == 9


def test_load_queries_from_db_uses_explicit_path(tmp_path):
    """The acquisition stage must honor --db instead of resolving config.yaml DB."""
    from stratum.stages.acquisition import load_queries_from_db

    db_path = tmp_path / "custom.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            status TEXT
        );
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT,
            intent TEXT,
            status TEXT,
            thread_id TEXT
        );
        INSERT INTO threads (id, status) VALUES ('et-active', 'active');
        INSERT INTO threads (id, status) VALUES ('et-cooling', 'cooling');
        INSERT INTO threads (id, status) VALUES ('et-dormant', 'dormant');
        INSERT INTO queries VALUES ('q1', 'HBM4 today', 'en', 'detection', 'active', NULL);
        INSERT INTO queries VALUES ('q2', 'NAND today', 'ja', 'detection', 'active', 'et-active');
        INSERT INTO queries VALUES ('q3', 'cooling followup', 'en', 'verification', 'active', 'et-cooling');
        INSERT INTO queries VALUES ('q4', 'old context', 'en', 'context', 'active', NULL);
        INSERT INTO queries VALUES ('q5', 'dormant thread', 'en', 'detection', 'active', 'et-dormant');
        INSERT INTO queries VALUES ('q6', 'inactive query', 'en', 'detection', 'inactive', NULL);
        INSERT INTO queries VALUES ('q7', 'verify HBM4', 'en', 'verification', 'active', NULL);
    """)
    conn.close()

    queries = load_queries_from_db("storage", str(db_path), "/unused/workspace")

    assert [q["id"] for q in queries] == ["q1", "q2", "q3", "q7"]
    assert queries[0]["text"] == "HBM4 today"
    assert queries[1]["locale"] == "ja"
    assert queries[2]["text"] == "cooling followup"
    assert queries[3]["intent"] == "verification"
    assert queries[0]["dimension"] == "db"


def test_load_queries_from_db_preserves_dimension(tmp_path):
    """DB-backed Search should keep coverage dimensions seeded from queries.yaml."""
    from stratum.stages.acquisition import load_queries_from_db

    db_path = tmp_path / "custom.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            status TEXT
        );
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT,
            intent TEXT,
            dimension TEXT,
            include_domains TEXT,
            status TEXT,
            thread_id TEXT
        );
        INSERT INTO queries VALUES (
            'q-tech',
            'Samsung HBM4',
            'en',
            'detection',
            'technology',
            '["semiconductor.samsung.com"]',
            'active',
            NULL
        );
        INSERT INTO queries VALUES (
            'q-fin',
            'Micron earnings NAND',
            'en',
            'verification',
            'financial',
            NULL,
            'active',
            NULL
        );
    """)
    conn.close()

    queries = load_queries_from_db("storage", str(db_path), "/unused/workspace")

    assert [q["dimension"] for q in queries] == ["technology", "financial"]
    assert queries[0]["include_domains"] == ["semiconductor.samsung.com"]
    assert "include_domains" not in queries[1]


def test_load_queries_from_db_normalizes_include_domains(tmp_path):
    from stratum.stages.acquisition import load_queries_from_db

    db_path = tmp_path / "custom.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            status TEXT
        );
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT,
            intent TEXT,
            dimension TEXT,
            include_domains TEXT,
            status TEXT,
            thread_id TEXT
        );
        INSERT INTO queries VALUES (
            'q-source',
            'Samsung HBM4',
            'en',
            'detection',
            'technology',
            '["https://www.Semiconductor.Samsung.com/newsroom/", "m.reuters.com"]',
            'active',
            NULL
        );
    """)
    conn.close()

    queries = load_queries_from_db("storage", str(db_path), "/unused/workspace")

    assert queries[0]["include_domains"] == ["semiconductor.samsung.com", "reuters.com"]


def test_load_queries_flat_supports_intent_grouped_yaml(tmp_path):
    """Search YAML can evolve to queries: intent -> dimension -> locale -> list."""
    from stratum.stages.acquisition import load_queries_flat

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
queries:
  detection:
    technology:
      en:
        - id: q-detect-en
          text: "Samsung HBM ${CURRENT_YEAR}"
          include_domains: ["semiconductor.samsung.com"]
      zh-CN:
        - "长江存储 ${CURRENT_MONTH_ZH}"
    platform_demand:
      en:
        - "NVIDIA Rubin HBM4 demand"
  verification:
    financial:
      en:
        - query: "Micron NAND ${CURRENT_MONTH_EN}"
          id: q-verify-en
""")

    queries = load_queries_flat(str(queries_path), "2026-05-30")

    assert queries == [
        {
            "id": "q-detect-en",
            "text": "Samsung HBM 2026",
            "locale": "en",
            "intent": "detection",
            "dimension": "technology",
            "include_domains": ["semiconductor.samsung.com"],
        },
        {
            "id": "q-detection-technology-001",
            "text": "长江存储 5月",
            "locale": "zh-CN",
            "intent": "detection",
            "dimension": "technology",
        },
        {
            "id": "q-detection-platform_demand-002",
            "text": "NVIDIA Rubin HBM4 demand",
            "locale": "en",
            "intent": "detection",
            "dimension": "platform_demand",
        },
        {
            "id": "q-verify-en",
            "text": "Micron NAND May",
            "locale": "en",
            "intent": "verification",
            "dimension": "financial",
        },
    ]


def test_load_queries_flat_normalizes_include_domains(tmp_path):
    from stratum.stages.acquisition import load_queries_flat

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
queries:
  detection:
    technology:
      en:
        - text: "Samsung HBM4"
          include_domains:
            - "https://www.Semiconductor.Samsung.com/newsroom/"
            - "m.reuters.com"
            - "reuters.com"
""")

    queries = load_queries_flat(str(queries_path), "2026-05-30")

    assert queries[0]["include_domains"] == ["semiconductor.samsung.com", "reuters.com"]


def test_load_queries_flat_rejects_malformed_include_domains(tmp_path):
    from stratum.stages.acquisition import load_queries_flat
    import pytest

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
queries:
  detection:
    technology:
      en:
        - text: "Samsung HBM4"
          include_domains:
            value: "not a list"
""")

    with pytest.raises(ValueError, match="include_domains"):
        load_queries_flat(str(queries_path), "2026-05-30")


def test_load_queries_flat_still_supports_intent_locale_yaml(tmp_path):
    """The simpler queries: intent -> locale -> list form stays supported."""
    from stratum.stages.acquisition import load_queries_flat

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
queries:
  detection:
    en:
      - "Samsung HBM ${CURRENT_YEAR}"
""")

    queries = load_queries_flat(str(queries_path), "2026-05-30")

    assert queries == [
        {
            "id": "q-detection-general-000",
            "text": "Samsung HBM 2026",
            "locale": "en",
            "intent": "detection",
            "dimension": "general",
        }
    ]


def test_load_queries_flat_recognizes_bcp47_locale_keys(tmp_path):
    """Simple intent->locale query YAML should not drop script/region variants."""
    from stratum.stages.acquisition import load_queries_flat

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
queries:
  detection:
    zh-Hans-CN:
      - "长江存储 ${CURRENT_YEAR}"
    en-US:
      - "Micron memory ${CURRENT_MONTH_EN}"
    zh-cn:
      - "长鑫存储 ${CURRENT_MONTH_ZH}"
""")

    queries = load_queries_flat(str(queries_path), "2026-05-30")

    assert queries == [
        {
            "id": "q-detection-general-000",
            "text": "长江存储 2026",
            "locale": "zh-Hans-CN",
            "intent": "detection",
            "dimension": "general",
        },
        {
            "id": "q-detection-general-001",
            "text": "Micron memory May",
            "locale": "en-US",
            "intent": "detection",
            "dimension": "general",
        },
        {
            "id": "q-detection-general-002",
            "text": "长鑫存储 5月",
            "locale": "zh-cn",
            "intent": "detection",
            "dimension": "general",
        },
    ]


def test_load_queries_flat_rejects_legacy_seed_and_gap_yaml(tmp_path):
    """Stage acquisition should not silently accept the removed query schema."""
    from stratum.stages.acquisition import load_queries_flat
    import pytest

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
seed_queries:
  en:
    - "Samsung HBM ${CURRENT_YEAR}"
gap_searches:
  - query: "Micron NAND ${CURRENT_MONTH_EN}"
    locale: en
""")

    with pytest.raises(ValueError, match="structured queries"):
        load_queries_flat(str(queries_path), "2026-05-30")


def test_resolve_queries_falls_back_to_yaml_when_db_has_no_active_queries(tmp_path, capsys):
    """An existing but empty DB must not create a zero-query acquisition run."""
    from stratum.stages.acquisition import resolve_queries

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
queries:
  detection:
    general:
      en:
        - "Samsung HBM ${CURRENT_YEAR}"
""")

    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE threads (id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT,
            intent TEXT,
            status TEXT,
            thread_id TEXT
        );
    """)
    conn.close()

    queries, source = resolve_queries(
        "storage", "2026-05-30", str(db_path), str(queries_path), "/unused/workspace"
    )

    assert source == "YAML"
    assert queries == [
        {
            "id": "q-detection-general-000",
            "text": "Samsung HBM 2026",
            "locale": "en",
            "intent": "detection",
            "dimension": "general",
        }
    ]
    assert "falling back to YAML" in capsys.readouterr().err


def test_discovery_candidate_rows_mark_curator_selection():
    from stratum.stages.acquisition import discovery_candidate_rows
    from stratum.sourcing.discovery import ResultSet, SearchResult

    selected = SearchResult(
        url="https://example.com/selected",
        title="Selected HBM story",
        snippet="",
        locale="en",
        engine="tavily",
        query_id="q1",
    ).with_domain()
    rejected = SearchResult(
        url="https://example.com/rejected",
        title="Rejected HBM story",
        snippet="",
        locale="en",
        engine="tavily",
        query_id="q1",
    ).with_domain()
    result_set = ResultSet(results=[selected], raw_results=[selected, rejected])

    rows = discovery_candidate_rows(result_set)

    assert [row["status"] for row in rows] == ["selected", "rejected"]
    assert rows[0]["selected"] is True
    assert rows[1]["reason"] == "curation pruned"


def test_discovery_observations_are_pre_curation_records():
    from stratum.sourcing.discovery import Query, SearchResult
    from stratum.sourcing.discovery.observations import observations_from_results

    query = Query(
        id="q1",
        text="HBM4 qualification",
        locale="en",
        intent="detection",
        dimension="technology",
    )
    result = SearchResult(
        url="https://www.example.com/story",
        title="HBM4 qualification advances",
        snippet="NVIDIA platform qualification update",
        locale="en",
        published_at="2026-05-31",
        engine="tavily",
        query_id="q1",
        query_dimension="technology",
        score=0.91,
    )

    rows = observations_from_results([result], [query])

    assert rows[0]["source"] == "tavily"
    assert rows[0]["access"] == "discovery"
    assert rows[0]["source_domain"] == "example.com"
    assert rows[0]["query_used"] == "HBM4 qualification"
    assert rows[0]["query_dimension"] == "technology"
    assert "score" not in rows[0]
    assert "status" not in rows[0]
    assert "selected" not in rows[0]
    assert "reason" not in rows[0]


def test_resolve_queries_prefers_db_when_active_queries_exist(tmp_path):
    """DB-backed discovery remains preferred when it has active daily queries."""
    from stratum.stages.acquisition import resolve_queries

    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text("""
queries:
  detection:
    general:
      en:
        - "YAML baseline"
""")

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE threads (id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE queries (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            locale TEXT,
            intent TEXT,
            status TEXT,
            thread_id TEXT
        );
        INSERT INTO queries VALUES ('db-q', 'DB followup', 'en', 'detection', 'active', NULL);
    """)
    conn.close()

    queries, source = resolve_queries(
        "storage", "2026-05-30", str(db_path), str(queries_path), "/unused/workspace"
    )

    assert source == "DB"
    assert [q["id"] for q in queries] == ["db-q"]


# ============================================================
# EXECUTOR
# ============================================================

def test_executor_logs_summary_without_sys_name_error(capsys):
    """execute() should complete its stderr summary path."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    class FakeEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            return [
                SearchResult(
                    url=f"https://example.com/{query_id}",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                )
            ]

    results, stats = execute(
        queries=[Query(id="q1", text="HBM4 ${CURRENT_YEAR}", locale="en")],
        engines={"fake": FakeEngine()},
        routing={"en": ["fake"]},
        max_rps={"fake": 100},
        max_retries={"fake": 0},
        backoff_base={"fake": 0},
        date="2026-05-30",
        workers=1,
    )

    assert len(results) == 1
    assert stats[0].status == "success"
    assert "Search: 1/1 queries OK" in capsys.readouterr().err


def test_executor_passes_query_include_domains_to_engine():
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    captured = {}

    class FakeEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            captured["include_domains"] = kwargs.get("include_domains")
            return [
                SearchResult(
                    url="https://semiconductor.samsung.com/newsroom/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                )
            ]

    _results, stats = execute(
        queries=[
            Query(
                id="q1",
                text="Samsung HBM4",
                locale="en",
                include_domains=["semiconductor.samsung.com"],
            )
        ],
        engines={"fake": FakeEngine()},
        routing={"en": ["fake"]},
        max_rps={"fake": 100},
        max_retries={"fake": 0},
        backoff_base={"fake": 0},
        date="2026-05-30",
        workers=1,
    )

    assert captured["include_domains"] == ["semiconductor.samsung.com"]
    assert stats[0].include_domains == ["semiconductor.samsung.com"]
    assert stats[0].to_dict()["include_domains"] == ["semiconductor.samsung.com"]


def test_executor_skips_engines_that_cannot_honor_include_domains():
    """A source-scoped query must not silently widen on an unsupported engine."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    calls = []

    class BroadEngine:
        supports_include_domains = False

        def search(self, text, locale, query_id, date, **kwargs):
            calls.append("broad")
            return [
                SearchResult(
                    url="https://broad.example.com/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="broad",
                    query_id=query_id,
                )
            ]

    class DomainEngine:
        supports_include_domains = True

        def search(self, text, locale, query_id, date, **kwargs):
            calls.append(("domain", kwargs.get("include_domains")))
            return [
                SearchResult(
                    url="https://digitimes.com/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="domain",
                    query_id=query_id,
                )
            ]

    results, stats = execute(
        queries=[
            Query(
                id="q-cn",
                text="长鑫 长江存储 美光 存储 供应链",
                locale="zh-CN",
                include_domains=["digitimes.com"],
            )
        ],
        engines={"broad": BroadEngine(), "domain": DomainEngine()},
        routing={"zh-CN": ["broad", "domain"]},
        max_rps={"broad": 100, "domain": 100},
        max_retries={"broad": 0, "domain": 0},
        backoff_base={"broad": 0, "domain": 0},
        date="2026-05-30",
        workers=1,
    )

    assert calls == [("domain", ["digitimes.com"])]
    assert len(results) == 1
    assert stats[0].engine_used == "domain"
    assert stats[0].status == "fallback"


def test_run_search_low_yield_query_stats_expose_include_domains(monkeypatch):
    """Domain-scoped low-yield queries need visible filters for debugging recall."""
    from stratum.sourcing.discovery import run_search

    class EmptyEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            return []

    monkeypatch.setattr(
        "stratum.sourcing.discovery.engine.create_engines",
        lambda engine_configs, api_keys: {"fake": EmptyEngine()},
    )

    config = {
        "routing": {"en": ["fake"]},
        "engines": {"fake": {"max_rps": 100, "max_retries": 0, "backoff_base": 0}},
        "source_weights": {"media": 0.6},
        "classifications": {},
        "entities": [],
        "terms": [],
        "max_per_locale": 10,
        "max_per_source": 10,
        "total_cap": 10,
    }

    result_set = run_search(
        queries=[
            {
                "id": "q-official",
                "text": "Samsung HBM4",
                "locale": "en",
                "include_domains": ["semiconductor.samsung.com"],
            }
        ],
        config=config,
        api_keys={},
        date="2026-05-30",
        workers=1,
    )

    low_yield = result_set.to_stats_json()["diagnostics"]["low_yield_queries"]
    assert low_yield[0]["status"] == "no_results"
    assert low_yield[0]["include_domains"] == ["semiconductor.samsung.com"]
    performance = result_set.to_stats_json()["diagnostics"]["query_performance"]
    assert performance["records"][0]["query_id"] == "q-official"
    assert performance["records"][0]["recommendation"] == "keep_collecting"


def test_executor_dedupes_by_canonical_url():
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    class FakeEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            return [
                SearchResult(
                    url="https://www.example.com/story?utm_campaign=x",
                    title="A",
                    snippet="",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                ),
                SearchResult(
                    url="https://m.example.com/story/",
                    title="A duplicate",
                    snippet="",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                ),
            ]

    results, stats = execute(
        queries=[Query(id="q1", text="HBM4", locale="en")],
        engines={"fake": FakeEngine()},
        routing={"en": ["fake"]},
        max_rps={"fake": 100},
        max_retries={"fake": 0},
        backoff_base={"fake": 0},
        date="2026-05-30",
        workers=1,
    )

    assert stats[0].results_count == 1
    assert len(results) == 1
    assert results[0].canonical_url == "https://example.com/story"


def test_executor_preserves_failure_error():
    """execute() should expose engine errors for search diagnostics."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query

    class BrokenEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            raise RuntimeError("bad payload")

    results, stats = execute(
        queries=[Query(id="q1", text="HBM4", locale="en", intent="detection")],
        engines={"broken": BrokenEngine()},
        routing={"en": ["broken"]},
        max_rps={"broken": 100},
        max_retries={"broken": 0},
        backoff_base={"broken": 0},
        date="2026-05-30",
        workers=1,
    )

    assert results == []
    assert stats[0].status == "failed"
    assert stats[0].locale == "en"
    assert stats[0].intent == "detection"
    assert "RuntimeError: bad payload" in stats[0].error


def test_executor_preserves_fallback_attempt_errors():
    """All-engine failures should keep the full fallback attempt chain."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query

    class BrokenBocha:
        def search(self, text, locale, query_id, date, **kwargs):
            raise RuntimeError("bocha down")

    class BrokenTavily:
        def search(self, text, locale, query_id, date, **kwargs):
            raise RuntimeError("tavily quota")

    results, stats = execute(
        queries=[Query(id="q-cn", text="HBM4", locale="zh-CN", intent="detection")],
        engines={"bocha": BrokenBocha(), "tavily": BrokenTavily()},
        routing={"zh-CN": ["bocha", "tavily"]},
        max_rps={"bocha": 100, "tavily": 100},
        max_retries={"bocha": 0, "tavily": 0},
        backoff_base={"bocha": 0, "tavily": 0},
        date="2026-05-30",
        workers=1,
    )

    assert results == []
    assert stats[0].status == "failed"
    assert "bocha: RuntimeError: bocha down" in stats[0].error
    assert "tavily: RuntimeError: tavily quota" in stats[0].error

    serialized = stats[0].to_dict()
    assert serialized["engine_attempts"] == [
        {
            "engine": "bocha",
            "attempt": 0,
            "status": "failed",
            "error": "bocha: RuntimeError: bocha down",
        },
        {
            "engine": "tavily",
            "attempt": 0,
            "status": "failed",
            "error": "tavily: RuntimeError: tavily quota",
        },
    ]


def test_executor_falls_back_when_primary_engine_is_unavailable():
    """Missing primary engine should not prevent locale fallback from running."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    class FallbackEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            return [
                SearchResult(
                    url="https://fallback.example.com/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="tavily",
                    query_id=query_id,
                )
            ]

    results, stats = execute(
        queries=[Query(id="q1", text="HBM4", locale="zh-CN", intent="detection")],
        engines={"tavily": FallbackEngine()},
        routing={"zh-CN": ["bocha", "tavily"]},
        max_rps={"tavily": 100},
        max_retries={"tavily": 0},
        backoff_base={"tavily": 0},
        date="2026-05-30",
        workers=1,
    )

    assert len(results) == 1
    assert stats[0].engine_used == "tavily"
    assert stats[0].status == "fallback"


def test_executor_uses_engine_health_to_deprioritize_weak_primary():
    """Health recommendations can reorder fallback without dropping engines."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    calls = []

    class BochaEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            calls.append("bocha")
            return [
                SearchResult(
                    url="https://bocha.example.com/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="bocha",
                    query_id=query_id,
                )
            ]

    class TavilyEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            calls.append("tavily")
            return [
                SearchResult(
                    url="https://tavily.example.com/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="tavily",
                    query_id=query_id,
                )
            ]

    results, stats = execute(
        queries=[Query(id="q1", text="HBM4", locale="zh-CN", intent="detection")],
        engines={"bocha": BochaEngine(), "tavily": TavilyEngine()},
        routing={"zh-CN": ["bocha", "tavily"]},
        max_rps={"bocha": 100, "tavily": 100},
        max_retries={"bocha": 0, "tavily": 0},
        backoff_base={"bocha": 0, "tavily": 0},
        date="2026-05-30",
        workers=1,
        engine_health={
            "bocha": {"recommendation": "avoid"},
            "tavily": {"recommendation": "healthy"},
        },
    )

    assert calls == ["tavily"]
    assert results[0].engine == "tavily"
    assert stats[0].engine_used == "tavily"
    assert stats[0].status == "success"


def test_executor_marks_provider_exhausted_without_retrying_quota_errors():
    """Quota/auth failures are provider exhaustion, not transient retry signals."""
    from stratum.subsystems.monitoring.engine_health import score_search_engine_health
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query

    calls = []

    class QuotaEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            calls.append(query_id)
            raise RuntimeError("HTTP 433: pay-as-you-go limit exceeded")

    results, stats = execute(
        queries=[Query(id="q1", text="HBM4", locale="en", intent="detection")],
        engines={"tavily": QuotaEngine()},
        routing={"en": ["tavily"]},
        max_rps={"tavily": 100},
        max_retries={"tavily": 2},
        backoff_base={"tavily": 0},
        date="2026-05-30",
        workers=1,
    )

    assert results == []
    assert calls == ["q1"]
    assert stats[0].engine_attempts[0]["status"] == "provider_exhausted"
    health = score_search_engine_health([stats[0].to_dict()])
    assert health["tavily"]["recommendation"] == "avoid"
    assert health["tavily"]["provider_exhausted"] == 1


def test_executor_marks_http_403_provider_exhausted():
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query

    calls = []

    class ForbiddenEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            calls.append(query_id)
            raise RuntimeError("403 Client Error: Forbidden for url")

    _results, stats = execute(
        queries=[Query(id="q1", text="HBM4", locale="zh-CN", intent="detection")],
        engines={"bocha": ForbiddenEngine()},
        routing={"zh-CN": ["bocha"]},
        max_rps={"bocha": 100},
        max_retries={"bocha": 2},
        backoff_base={"bocha": 0},
        date="2026-05-30",
        workers=1,
    )

    assert calls == ["q1"]
    assert stats[0].engine_attempts[0]["status"] == "provider_exhausted"


def test_routing_policy_preserves_configured_chain_while_applying_health():
    """RoutingPolicy owns route decisions; executor only consumes the chain."""
    from stratum.sourcing.discovery.routing import RoutingPolicy

    policy = RoutingPolicy(
        routing={"zh-CN": ["bocha", "tavily", "fallback"]},
        engine_health={
            "bocha": {"recommendation": "avoid"},
            "tavily": {"recommendation": "healthy"},
            "fallback": {"recommendation": "watch"},
        },
    )

    decision = policy.decide("zh-Hans-CN")

    assert decision.matched_locale == "zh-CN"
    assert decision.configured_order == ["bocha", "tavily", "fallback"]
    assert decision.selected_order == ["tavily", "fallback", "bocha"]
    assert decision.health_applied is True


def test_executor_routes_locale_variants_to_configured_parent_locale():
    """BCP47 script/region variants should keep the intended engine chain."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    class FakeEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            return [
                SearchResult(
                    url="https://bocha.example.com/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="bocha",
                    query_id=query_id,
                )
            ]

    results, stats = execute(
        queries=[Query(id="q1", text="长江存储", locale="zh-Hans-CN", intent="detection")],
        engines={"bocha": FakeEngine()},
        routing={"zh-CN": ["bocha"], "en": ["tavily"]},
        max_rps={"bocha": 100},
        max_retries={"bocha": 0},
        backoff_base={"bocha": 0},
        date="2026-05-30",
        workers=1,
    )

    assert len(results) == 1
    assert stats[0].engine_used == "bocha"
    assert stats[0].status == "success"


def test_executor_passes_query_metadata_to_engine():
    """Engine payload selection needs intent and dimension, not only text/locale."""
    from stratum.sourcing.discovery.executor import execute
    from stratum.sourcing.discovery import Query, SearchResult

    seen = {}

    class FakeEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            seen.update(kwargs)
            return [
                SearchResult(
                    url="https://example.com/story",
                    title=text,
                    snippet="",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                )
            ]

    execute(
        queries=[
            Query(
                id="q1",
                text="HBM pricing",
                locale="en",
                intent="verification",
                dimension="market_pricing",
            )
        ],
        engines={"fake": FakeEngine()},
        routing={"en": ["fake"]},
        max_rps={"fake": 100},
        max_retries={"fake": 0},
        backoff_base={"fake": 0},
        date="2026-05-30",
        workers=1,
    )

    assert seen == {
        "intent": "verification",
        "dimension": "market_pricing",
    }


def test_run_search_records_query_failures_when_no_engine_keys(capsys):
    """No usable engines should still produce per-query diagnostics."""
    from stratum.sourcing.discovery import run_search

    config = {
        "routing": {"en": ["tavily"]},
        "engines": {"tavily": {"max_rps": 100, "max_retries": 0, "backoff_base": 0}},
        "source_weights": {"media": 0.6},
        "classifications": {},
        "entities": [],
        "terms": [],
        "max_per_locale": 10,
        "max_per_source": 3,
        "total_cap": 10,
    }

    result_set = run_search(
        queries=[{"id": "q1", "text": "HBM4", "locale": "en", "intent": "detection"}],
        config=config,
        api_keys={},
        date="2026-05-30",
        workers=1,
    )

    assert result_set.results == []
    assert result_set.stats[0].status == "failed"
    assert result_set.stats[0].error == "tavily: engine not configured"
    assert result_set.stats[0].query_text == "HBM4"
    assert result_set.stats[0].dimension == "general"
    assert result_set.diagnostics["low_yield_queries"][0]["query_id"] == "q1"
    assert result_set.diagnostics["engine_health"]["tavily"]["recommendation"] == "avoid"
    assert result_set.diagnostics["engine_configuration"] == {
        "configured_engines": ["tavily"],
        "usable_engines": [],
        "missing_api_keys": ["tavily"],
        "unreachable_locales": [{"locale": "en", "configured_order": ["tavily"]}],
    }
    assert "No usable search engines configured" in capsys.readouterr().err


def test_run_search_stats_include_curation_diagnostics(monkeypatch):
    """raw.stats.json should explain source/locale coverage and floor gaps."""
    from stratum.sourcing.discovery import run_search
    from stratum.sourcing.discovery import SearchResult

    class FakeEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            return [
                SearchResult(
                    url="https://media.example.com/a",
                    title="Samsung HBM4 update",
                    snippet="Samsung memory roadmap",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                ),
                SearchResult(
                    url="https://media.example.com/b",
                    title="Micron NAND update",
                    snippet="Micron storage roadmap",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                ),
            ]

    monkeypatch.setattr(
        "stratum.sourcing.discovery.engine.create_engines",
        lambda engine_configs, api_keys: {"fake": FakeEngine()},
    )

    config = {
        "routing": {"en": ["fake"], "zh-CN": ["missing"]},
        "engines": {"fake": {"max_rps": 100, "max_retries": 0, "backoff_base": 0}},
        "source_weights": {"media": 0.6, "official": 1.0},
        "classifications": {"media": ["media.example.com"]},
        "entities": [],
        "terms": [],
        "max_per_locale": 10,
        "max_per_source": 10,
        "total_cap": 10,
        "min_per_source_type": {"official": 1, "media": 1},
    }

    result_set = run_search(
        queries=[
            {
                "id": "q-en",
                "text": "HBM4",
                "locale": "en",
                "intent": "detection",
                "dimension": "platform_demand",
            },
            {
                "id": "q-zh",
                "text": "HBM4",
                "locale": "zh-CN",
                "intent": "detection",
                "dimension": "technology",
            },
        ],
        config=config,
        api_keys={},
        date="2026-05-30",
        workers=1,
    )

    stats = result_set.to_stats_json()
    diagnostics = stats["diagnostics"]

    assert diagnostics["raw_by_locale"] == {"en": 2}
    assert diagnostics["raw_by_dimension"] == {"platform_demand": 2}
    assert diagnostics["curated_by_dimension"] == {"platform_demand": 2}
    assert {"dimension": "technology", "queries": 1, "raw": 0, "curated": 0} in diagnostics["dimension_coverage"]
    assert diagnostics["curated_by_source_type"] == {"media": 2}
    assert diagnostics["source_type_gaps"] == [
        {"source_type": "official", "minimum": 1, "raw_available": 0, "curated": 0, "shortfall": 1}
    ]
    assert {"locale": "zh-CN", "queries": 1, "raw": 0, "curated": 0} in diagnostics["locale_coverage"]
    assert diagnostics["top_source_domains"] == [
        {"source_domain": "media.example.com", "raw": 2, "curated": 2}
    ]
    assert diagnostics["low_yield_queries"][0]["query_id"] == "q-zh"


def test_search_diagnostics_normalize_bad_external_grouping_keys():
    from stratum.sourcing.discovery import build_diagnostics
    from stratum.sourcing.discovery import Query, QueryStats, SearchResult

    diagnostics = build_diagnostics(
        queries=[Query(id="q1", text="HBM4", locale="en")],
        raw_results=[
            SearchResult(
                url="https://example.com/a",
                title="A",
                snippet="",
                locale=False,
                source_type_hint="media",
                source_domain="example.com",
                query_dimension="technology",
            )
        ],
        curated_results=[],
        query_stats=[
            QueryStats(
                query_id="q1",
                engine_used="tavily",
                status="success",
                results_count=1,
                locale="en",
                dimension="technology",
            )
        ],
        config={"routing": {"en": ["tavily"]}},
    )

    assert diagnostics["raw_by_locale"] == {"unknown": 1}
    assert {"locale": "unknown", "queries": 0, "raw": 1, "curated": 0} in diagnostics["locale_coverage"]


def test_run_search_engine_configuration_normalizes_non_string_route_keys(monkeypatch):
    from stratum.sourcing.discovery import run_search

    monkeypatch.setattr(
        "stratum.sourcing.discovery.engine.create_engines",
        lambda engine_configs, api_keys: {},
    )

    result_set = run_search(
        queries=[{"id": "q1", "text": "HBM4", "locale": "en", "intent": "detection"}],
        config={
            "routing": {False: ["tavily"], "en": ["tavily"]},
            "engines": {"tavily": {"max_rps": 100, "max_retries": 0, "backoff_base": 0}},
            "source_weights": {"media": 0.6},
            "classifications": {},
            "entities": [],
            "terms": [],
            "max_per_locale": 10,
            "max_per_source": 3,
            "total_cap": 10,
        },
        api_keys={},
        date="2026-05-30",
        workers=1,
    )

    assert result_set.diagnostics["engine_configuration"]["unreachable_locales"] == [
        {"locale": "unknown", "configured_order": ["tavily"]},
        {"locale": "en", "configured_order": ["tavily"]},
    ]


def test_run_search_diagnostics_track_include_domain_coverage(monkeypatch):
    """Scoped queries should expose which configured domains produced evidence."""
    from stratum.sourcing.discovery import run_search
    from stratum.sourcing.discovery import SearchResult

    class FakeEngine:
        def search(self, text, locale, query_id, date, **kwargs):
            return [
                SearchResult(
                    url="https://www.digitimes.com/news/a",
                    title="CXMT memory supply chain",
                    snippet="",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                ),
                SearchResult(
                    url="https://other.example.com/news/b",
                    title="Other memory update",
                    snippet="",
                    locale=locale,
                    engine="fake",
                    query_id=query_id,
                ),
            ]

    monkeypatch.setattr(
        "stratum.sourcing.discovery.engine.create_engines",
        lambda engine_configs, api_keys: {"fake": FakeEngine()},
    )

    config = {
        "routing": {"en": ["fake"]},
        "engines": {"fake": {"max_rps": 100, "max_retries": 0, "backoff_base": 0}},
        "source_weights": {"media": 0.6},
        "classifications": {"media": ["digitimes.com", "other.example.com"]},
        "entities": [],
        "terms": [],
        "max_per_locale": 10,
        "max_per_source": 10,
        "total_cap": 10,
    }

    result_set = run_search(
        queries=[
            {
                "id": "q-digitimes",
                "text": "memory supply chain",
                "locale": "en",
                "include_domains": ["digitimes.com", "thelec.net"],
            }
        ],
        config=config,
        api_keys={},
        date="2026-05-30",
        workers=1,
    )

    assert result_set.diagnostics["domain_filter_coverage"] == [
        {
            "include_domain": "digitimes.com",
            "queries": 1,
            "failed_queries": 0,
            "raw": 1,
            "curated": 1,
        },
        {
            "include_domain": "thelec.net",
            "queries": 1,
            "failed_queries": 0,
            "raw": 0,
            "curated": 0,
        },
    ]


# ============================================================
# ENGINE
# ============================================================

def test_create_engines():
    """Engine factory creates correct instances."""
    from stratum.sourcing.discovery.engine import create_engines, BochaEngine, TavilyEngine

    engine_configs = {
        "bocha": {"freshness": "oneDay", "count": 10},
        "tavily": {
            "search_depth": "advanced",
            "max_results": 10,
            "include_domains": {"ja": ["nikkei.com"]},
            "topic_by_intent": {"verification": "general"},
            "topic_by_dimension": {"financial": "general"},
        },
    }
    api_keys = {"bocha": "fake-bocha-key", "tavily": "fake-tavily-key"}

    engines = create_engines(engine_configs, api_keys)
    assert "bocha" in engines
    assert "tavily" in engines
    assert isinstance(engines["bocha"], BochaEngine)
    assert isinstance(engines["tavily"], TavilyEngine)
    assert engines["bocha"].api_key == "fake-bocha-key"
    assert engines["tavily"].include_domains == {"ja": ["nikkei.com"]}
    assert engines["tavily"].topic_by_intent == {"verification": "general"}
    assert engines["tavily"].topic_by_dimension == {"financial": "general"}

    # With no configs
    engines2 = create_engines({}, {})
    assert len(engines2) == 0

    print("  ✓ create_engines")


def test_create_engines_skips_engines_without_api_keys():
    """Missing API keys should not create engines that will only auth-fail."""
    from stratum.sourcing.discovery.engine import create_engines

    engine_configs = {
        "bocha": {"freshness": "oneDay", "count": 10},
        "tavily": {"search_depth": "advanced", "max_results": 10},
    }

    engines = create_engines(engine_configs, {"tavily": "fake-tavily-key"})

    assert set(engines) == {"tavily"}


def test_tavily_date_window_and_site_filter_helpers():
    """Tavily uses non-empty date ranges and converts site: syntax."""
    from stratum.sourcing.discovery.engine import TavilyEngine

    assert TavilyEngine._date_window("2026-05-30") == ("2026-05-30", "2026-05-31")

    cleaned, domains = TavilyEngine._extract_site_filters(
        'site:digitimes.com memory HBM OR site:nikkei.com NAND'
    )
    assert domains == ["digitimes.com", "nikkei.com"]
    assert "site:" not in cleaned
    assert "memory HBM" in cleaned


def test_tavily_include_domains_follow_locale_parent_fallback():
    """Domain-scoped Tavily routing should survive BCP47 locale variants."""
    from stratum.sourcing.discovery.engine import TavilyEngine

    engine = TavilyEngine(
        api_key="fake",
        include_domains={
            "en": ["reuters.com"],
            "zh-CN": ["digitimes.com"],
            "zh": ["fallback-cn.example"],
        },
    )

    assert engine._include_domains_for_locale("en-US") == ["reuters.com"]
    assert engine._include_domains_for_locale("zh-Hans-CN") == [
        "digitimes.com",
        "fallback-cn.example",
    ]
    assert engine._include_domains_for_locale("ZH-cn") == [
        "digitimes.com",
        "fallback-cn.example",
    ]


def test_tavily_topic_strategy_uses_site_intent_and_dimension(monkeypatch):
    """Tavily topic should be configurable by query shape and coverage purpose."""
    from stratum.sourcing.discovery.engine import TavilyEngine

    payloads = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    def fake_post(url, json, timeout):
        payloads.append(json)
        return FakeResponse()

    monkeypatch.setattr("stratum.sourcing.discovery.engine.requests.post", fake_post)

    engine = TavilyEngine(
        api_key="fake",
        topic="news",
        include_domains={"ja": ["nikkei.com"]},
        topic_by_intent={"verification": "general"},
        topic_by_dimension={"financial": "general"},
    )

    engine.search("HBM outlook", "en", "q1", intent="detection", dimension="technology")
    engine.search("HBM ASP", "en", "q2", intent="verification", dimension="technology")
    engine.search("Micron earnings", "en", "q3", intent="detection", dimension="financial")
    engine.search("site:digitimes.com HBM supply", "en", "q4", intent="detection", dimension="technology")
    engine.search("NAND supply", "ja", "q5", intent="detection", dimension="technology")
    engine.search(
        "Samsung HBM official",
        "en",
        "q6",
        intent="verification",
        dimension="technology",
        include_domains=["semiconductor.samsung.com", "news.samsung.com"],
    )

    assert payloads[0]["topic"] == "news"
    assert payloads[1]["topic"] == "general"
    assert payloads[2]["topic"] == "general"
    assert payloads[3]["topic"] == "general"
    assert payloads[3]["include_domains"] == ["digitimes.com"]
    assert payloads[4]["topic"] == "general"
    assert payloads[4]["include_domains"] == ["nikkei.com"]
    assert payloads[5]["topic"] == "general"
    assert payloads[5]["include_domains"] == [
        "semiconductor.samsung.com",
        "news.samsung.com",
    ]


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
        print("✅ All discovery subsystem tests passed")
    else:
        print(f"❌ {len(tests) - passed} test(s) failed")
        sys.exit(1)
