"""Collector unit tests."""

import json


def test_atom_feed_parses_namespaced_empty_link():
    from stratum.sourcing.watchlist.rss import _parse_atom_feed

    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Samsung HBM4 update</title>
        <link href="https://example.com/samsung-hbm4"/>
        <summary>HBM4 &amp; DRAM supply update</summary>
        <published>2026-05-30T12:00:00+09:00</published>
      </entry>
    </feed>
    """

    articles = _parse_atom_feed(xml)

    assert articles == [{
        "title": "Samsung HBM4 update",
        "url": "https://example.com/samsung-hbm4",
        "snippet": "HBM4 & DRAM supply update",
        "published_at": "2026-05-30",
    }]


def test_parse_rss_date_keeps_timezone_offset():
    from stratum.sourcing.watchlist.rss import _parse_rss_date

    assert _parse_rss_date("2026-05-30T12:00:00+09:00") == "2026-05-30"
    assert _parse_rss_date("Thu, 28 May 2026 15:02:21 GMT") == "2026-05-28"


def test_watchlist_common_normalizes_source_identity():
    from stratum.sourcing.watchlist.common import extract_domain, normalize_source_type

    assert extract_domain("https://www.micron.com/about/press/news") == "micron.com"
    assert extract_domain("https://m.reuters.com/technology") == "reuters.com"
    assert extract_domain("https://ww2.example.com/news") == "ww2.example.com"
    assert normalize_source_type("newsroom") == "official"
    assert normalize_source_type("rss") == "media"
    assert normalize_source_type("blog") == "blog"
    assert normalize_source_type("vendor_portal") == "unknown"


def test_watchlist_package_exports_stable_surface():
    import stratum.sourcing.watchlist as watchlist

    assert "collect" in watchlist.__all__
    assert "collect_with_stats" in watchlist.__all__
    assert "WatchlistRun" in watchlist.__all__
    assert "WatchlistSourceStats" in watchlist.__all__


def test_rss_uses_article_domain_and_canonical_source_type(monkeypatch):
    from stratum.sourcing.watchlist import rss

    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Micron HBM4 update</title>
        <link>https://www.micron.com/about/press/hbm4-update</link>
        <description>HBM4 production update</description>
        <pubDate>Thu, 28 May 2026 15:02:21 GMT</pubDate>
      </item>
    </channel></rss>
    """

    class Response:
        text = xml

        def raise_for_status(self):
            return None

    monkeypatch.setattr(rss.requests, "get", lambda *args, **kwargs: Response())

    results = rss.fetch_feed(
        "https://feeds.example.com/micron.xml",
        ["hbm4"],
        "micron-feed",
        "en",
        "newsroom",
    )

    assert len(results) == 1
    assert results[0].source_domain == "micron.com"
    assert results[0].source_type_hint == "official"


def test_rss_strict_mode_raises_on_malformed_xml(monkeypatch):
    from stratum.sourcing.watchlist import rss
    import pytest

    class Response:
        text = "<rss><channel><item>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(rss.requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(Exception):
        rss.fetch_feed(
            "https://example.com/feed.xml",
            ["hbm4"],
            "broken-feed",
            "en",
            "media",
            raise_on_error=True,
        )


def test_keyword_loading_and_matching(tmp_path):
    from stratum.sourcing.watchlist.keywords import load_keywords, match_keywords

    domain_dir = tmp_path / "domains" / "storage"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
companies:
  - id: samsung
    aliases:
      en: Samsung
      zh-CN: 三星电子
terms:
  - id: hbm4
    aliases:
      en: HBM4
      zh-CN: 高带宽内存
""")

    keywords = load_keywords("storage", str(tmp_path))

    assert "samsung" in keywords
    assert "hbm4" in keywords
    assert match_keywords("Samsung starts HBM4 production", "", keywords)
    assert not match_keywords("Unrelated smartphone accessory", "", keywords)


def test_watchlist_admission_keeps_storage_weak_signals():
    from stratum.sourcing.watchlist.keywords import admission_decision, match_keywords

    keywords = ["hbm4"]

    assert not match_keywords("Advanced packaging capacity expands", "Chiplet substrate demand grows", keywords)
    decision = admission_decision(
        "Advanced packaging capacity expands",
        "Chiplet substrate demand grows for AI accelerators",
        keywords,
        source_type="media",
        published_at="2026-05-30",
    )

    assert decision.status == "weak_signal"
    assert decision.accepted is True
    assert decision.score >= 0.55


def test_rss_admits_weak_signals_without_exact_keyword_match(monkeypatch):
    from stratum.sourcing.watchlist import rss

    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Advanced packaging capacity expands</title>
        <link>https://example.com/advanced-packaging</link>
        <description>Chiplet substrate demand grows for AI accelerators</description>
        <pubDate>Thu, 28 May 2026 15:02:21 GMT</pubDate>
      </item>
    </channel></rss>
    """

    class Response:
        text = xml

        def raise_for_status(self):
            return None

    monkeypatch.setattr(rss.requests, "get", lambda *args, **kwargs: Response())

    observations = []
    candidates = []
    results = rss.fetch_feed(
        "https://feeds.example.com/industry.xml",
        ["hbm4"],
        "industry-feed",
        "en",
        "media",
        observation_sink=observations,
        candidate_sink=candidates,
    )

    assert len(results) == 1
    assert results[0].query_dimension == "weak_signal"
    assert results[0].score >= 0.55
    assert observations[0]["title"] == "Advanced packaging capacity expands"
    assert observations[0]["parser"] == "rss"
    assert observations[0]["source_url"] == "https://feeds.example.com/industry.xml"
    assert "status" not in observations[0]
    assert "score" not in observations[0]
    assert "reason" not in observations[0]
    assert "matched_keywords" not in observations[0]
    assert candidates[0]["status"] == "weak_signal"
    assert candidates[0]["accepted"] is True


def test_source_registry_applies_access_defaults(tmp_path):
    from stratum.sourcing.watchlist.registry import get_active_sources

    domain_dir = tmp_path / "domains" / "storage"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
source_registry:
  sources:
    - id: micron-news
      access: direct_fetch
      status: active
      urls: ["https://example.com/news"]
    - id: wd-news
      access: browser
      status: active
      max_articles: 7
      urls: ["https://example.com/newsroom"]
    - id: inactive-feed
      access: rss
      status: inactive
      urls: ["https://example.com/feed"]
  defaults:
    direct_fetch:
      max_articles_per_url: 3
      timeout_seconds: 9
    browser:
      max_articles_per_url: 5
      timeout_seconds: 30
""")

    sources = get_active_sources("storage", str(tmp_path))
    by_id = {source["id"]: source for source in sources}

    assert set(by_id) == {"micron-news", "wd-news"}
    assert by_id["micron-news"]["max_articles"] == 3
    assert by_id["micron-news"]["max_articles_per_url"] == 3
    assert by_id["micron-news"]["timeout"] == 9
    assert by_id["wd-news"]["max_articles"] == 7
    assert by_id["wd-news"]["timeout"] == 30


def test_source_registry_uses_project_acquisition_priority(tmp_path):
    from stratum.sourcing.watchlist.registry import get_active_sources

    domain_dir = tmp_path / "domains" / "storage"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
source_registry:
  sources:
    - id: browser-source
      access: browser
      status: active
    - id: direct-source
      access: direct_fetch
      status: active
    - id: rss-source
      access: rss
      status: active
""")

    sources = get_active_sources("storage", str(tmp_path))

    assert [source["id"] for source in sources] == [
        "rss-source",
        "direct-source",
        "browser-source",
    ]


def test_source_registry_uses_health_within_access_priority(tmp_path):
    from stratum.sourcing.watchlist.registry import get_active_sources

    domain_dir = tmp_path / "domains" / "storage"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
source_registry:
  sources:
    - id: dry-rss
      access: rss
      status: active
    - id: healthy-rss
      access: rss
      status: active
    - id: direct-source
      access: direct_fetch
      status: active
""")

    sources = get_active_sources("storage", str(tmp_path), source_health={
        "dry-rss": {"selected_dry_streak": 4, "dry_streak": 2, "selected_rate": 0.0},
        "healthy-rss": {"selected_dry_streak": 0, "dry_streak": 0, "selected_rate": 2.0},
    })

    assert [source["id"] for source in sources] == [
        "healthy-rss",
        "dry-rss",
        "direct-source",
    ]


def test_source_health_tunes_watchlist_fetch_budget(tmp_path):
    from stratum.sourcing.watchlist.registry import get_active_sources

    domain_dir = tmp_path / "domains" / "storage"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
source_registry:
  sources:
    - id: high-yield
      access: direct_fetch
      status: active
      max_articles: 5
    - id: dry-source
      access: direct_fetch
      status: active
      max_articles: 10
    - id: date-poor
      access: direct_fetch
      status: active
      max_articles: 6
""")

    sources = get_active_sources("storage", str(tmp_path), source_health={
        "high-yield": {"selected_rate": 0.8, "selected_dry_streak": 0},
        "dry-source": {"selected_rate": 0.0, "selected_dry_streak": 4},
        "date-poor": {"selected_rate": 0.2, "dated_rate": 0.2},
    })
    by_id = {source["id"]: source for source in sources}

    assert by_id["high-yield"]["max_articles"] == 10
    assert by_id["dry-source"]["max_articles"] == 5
    assert by_id["date-poor"]["resolve_article_dates"] is True


def test_watchlist_health_loading_tolerates_null_historical_counters(tmp_path):
    from stratum.orchestrator.watchlist_runtime import load_watchlist_source_health

    channel_dir = tmp_path / "storage"
    channel_dir.mkdir(parents=True)
    (channel_dir / "source-daily.ndjson").write_text(json.dumps({
        "date": "2026-05-29",
        "source": "legacy-source",
        "scanned": True,
        "hits": None,
        "selected": None,
        "rejected": None,
        "http_code": None,
        "metadata": {"dated": None},
    }) + "\n")

    health = load_watchlist_source_health("storage", str(tmp_path))

    assert health["legacy-source"]["total_hits"] == 0
    assert health["legacy-source"]["selected_dry_streak"] == 1


def test_collector_runtime_wrapper_exposes_watchlist_runtime_surface():
    from stratum.orchestrator import collector_runtime, watchlist_runtime

    assert collector_runtime.run_watchlist is watchlist_runtime.run_watchlist
    assert collector_runtime.load_raw_results is watchlist_runtime.load_raw_results
    assert collector_runtime.update_post_collect_search_stats is (
        watchlist_runtime.update_post_collect_search_stats
    )
    assert collector_runtime.load_watchlist_source_health is (
        watchlist_runtime.load_watchlist_source_health
    )


def test_source_registry_applies_acquisition_budget_after_priority(tmp_path):
    from stratum.sourcing.watchlist.registry import get_active_sources

    domain_dir = tmp_path / "domains" / "storage"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
source_registry:
  budget:
    max_sources: 3
    max_per_access:
      rss: 2
      browser: 1
  sources:
    - id: rss-a
      access: rss
      status: active
    - id: rss-b
      access: rss
      status: active
    - id: rss-c
      access: rss
      status: active
    - id: direct-a
      access: direct_fetch
      status: active
    - id: browser-a
      access: browser
      status: active
""")

    sources = get_active_sources("storage", str(tmp_path))

    assert [source["id"] for source in sources] == ["rss-a", "rss-b", "direct-a"]


def test_acquisition_policy_documents_full_priority_order():
    from stratum.sourcing.policy import AcquisitionPolicy

    steps = AcquisitionPolicy().full_pipeline_steps()

    assert [step.name for step in steps] == [
        "rss",
        "direct_fetch",
        "browser",
        "discovery",
        "database",
    ]


def test_source_priority_scorer_explains_health_penalties():
    from stratum.sourcing.policy import SourcePriorityScorer

    score = SourcePriorityScorer().score(
        {"id": "source", "access": "rss"},
        {"source": {"http_error_streak": 2, "selected_dry_streak": 3, "dry_streak": 1}},
    )

    assert score.access_tier == 10
    assert score.health_penalty == 15
    assert "selected_dry_streak=3" in score.reason


def test_source_budget_policy_uses_access_cost_budget():
    from stratum.sourcing.policy import AcquisitionPolicy

    sources = [
        {"id": "rss-a", "access": "rss"},
        {"id": "direct-a", "access": "direct_fetch"},
        {"id": "browser-a", "access": "browser"},
        {"id": "rss-b", "access": "rss"},
    ]

    selected = AcquisitionPolicy().order_sources(
        sources,
        source_budget={
            "max_total_cost": 4,
            "min_per_access": {"rss": 1},
        },
    )

    assert [source["id"] for source in selected] == ["rss-a", "rss-b", "direct-a"]


def test_source_discovery_writes_review_only_candidates(monkeypatch, tmp_path):
    from stratum.sourcing.watchlist.discovery import discover_source_candidates, write_review_queue

    html = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>'

    class Response:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr("stratum.sourcing.watchlist.discovery.requests.get", lambda *args, **kwargs: Response())

    candidates = discover_source_candidates({
        "id": "example-newsroom",
        "urls": ["https://example.com/newsroom"],
    })
    queue_path = tmp_path / "candidates.jsonl"
    write_review_queue(candidates, str(queue_path))

    rows = [json.loads(line) for line in queue_path.read_text().splitlines()]
    assert {"source_id": "example-newsroom", "url": "https://example.com/feed.xml", "access": "rss", "reason": "html alternate feed link", "status": "review"} in rows
    assert {"source_id": "example-newsroom", "url": "https://example.com/feed/", "access": "rss", "reason": "common feed path", "status": "review"} in rows
    assert any(row["access"] == "sitemap" and row["status"] == "review" for row in rows)


def test_source_discovery_scans_registry_candidate_sources(monkeypatch, tmp_path):
    from stratum.sourcing.watchlist.discovery import discover_registry_candidates

    domain_dir = tmp_path / "domains" / "storage"
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text("""
source_registry:
  sources:
    - id: active-newsroom
      urls: ["https://active.example.com/news"]
      status: active
  candidate_sources:
    - id: review-newsroom
      urls: ["https://review.example.com/news"]
      status: review
""")

    class Response:
        text = '<html><link rel="alternate" type="application/rss+xml" href="/feed.xml"></html>'

        def raise_for_status(self):
            return None

    monkeypatch.setattr("stratum.sourcing.watchlist.discovery.requests.get", lambda *args, **kwargs: Response())

    candidates = discover_registry_candidates("storage", str(tmp_path))

    by_source = {candidate.source_id for candidate in candidates}
    assert {"active-newsroom", "review-newsroom"}.issubset(by_source)
    assert any(
        candidate.url == "https://review.example.com/feed.xml"
        and candidate.access == "rss"
        and candidate.status == "review"
        for candidate in candidates
    )


def test_source_expansion_scores_watchlist_funnel(tmp_path):
    from stratum.sourcing.watchlist.source_expansion import evaluate_source_expansion

    def write_jsonl(name, rows):
        (tmp_path / name).write_text("".join(json.dumps(row) + "\n" for row in rows))

    write_jsonl("watchlist_observations.jsonl", [
        {"source": "strong", "access": "rss", "url": f"https://strong.example.com/{i}", "title": "HBM", "locale": "en"}
        for i in range(5)
    ] + [
        {"source": "noisy", "access": "rss", "url": f"https://noisy.example.com/{i}", "title": "Off topic"}
        for i in range(5)
    ] + [
        {"source": "parser-gap", "access": "direct_fetch", "url": "https://gap.example.com/1", "title": "HBM"}
    ])
    write_jsonl("watchlist_candidates.jsonl", [
        {"source": "strong", "access": "rss", "url": f"https://strong.example.com/{i}", "accepted": True}
        for i in range(5)
    ] + [
        {"source": "noisy", "access": "rss", "url": f"https://noisy.example.com/{i}", "accepted": False}
        for i in range(5)
    ])
    (tmp_path / "watchlist_results.json").write_text(json.dumps([
        {
            "url": f"https://strong.example.com/{i}",
            "engine": "rss:strong",
            "published_at": "2026-05-30",
            "source_domain": "strong.example.com",
            "source_type_hint": "media",
        }
        for i in range(5)
    ]))
    (tmp_path / "raw.json").write_text(json.dumps([
        {"url": f"https://strong.example.com/{i}", "engine": "rss:strong"}
        for i in range(4)
    ]))

    report = evaluate_source_expansion(str(tmp_path))
    by_source = {row["source"]: row for row in report["sources"]}

    assert by_source["strong"]["recommendation"]["action"] == "promote"
    assert by_source["strong"]["metrics"]["raw_selected_rate"] == 0.8
    assert by_source["noisy"]["recommendation"]["action"] == "deprioritize"
    assert by_source["parser-gap"]["recommendation"]["action"] == "investigate_parser"


def test_direct_fetch_uses_article_page_date_not_list_page_date(monkeypatch):
    from stratum.sourcing.watchlist import direct_fetch

    list_html = """
    <html><body>
      <p>Micron Technology to report results on June 24, 2026</p>
      <h3><a href="/news/ssd-shipping">Industry-Leading 245TB Micron SSD Now Shipping</a></h3>
    </body></html>
    """
    article_html = """
    <html><body>
      <div class="field__item">May 5, 2026 at 9:01 AM EDT</div>
      <h1>Industry-Leading 245TB Micron SSD Now Shipping</h1>
    </body></html>
    """

    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        if url == "https://example.com/newsroom":
            return Response(list_html, url)
        if url == "https://example.com/news/ssd-shipping":
            return Response(article_html, url)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(direct_fetch.requests, "get", fake_get)

    results = direct_fetch.fetch_source({
        "id": "example-newsroom",
        "urls": ["https://example.com/newsroom"],
        "locale": "en",
        "category": "newsroom",
        "max_articles": 5,
        "resolve_article_dates": True,
    }, "2026-05-30")

    assert len(results) == 1
    assert results[0].published_at == "2026-05-05"
    assert results[0].source_domain == "example.com"
    assert results[0].source_type_hint == "official"


def test_direct_fetch_adapters_support_selectors_pagination_sitemap_and_admission(monkeypatch):
    from stratum.sourcing.watchlist import direct_fetch

    pages = {
        "https://example.com/news": '<a class="article-card" href="/news/advanced-packaging">Advanced packaging expands</a>',
        "https://example.com/page/2": "",
        "https://example.com/sitemap.xml": "<urlset><url><loc>https://example.com/news/hbm4-roadmap</loc></url></urlset>",
        "https://example.com/news/advanced-packaging": '<script type="application/ld+json">{"datePublished":"2026-05-29"}</script>',
        "https://example.com/news/hbm4-roadmap": '<script type="application/ld+json">{"datePublished":"2026-05-28"}</script>',
    }

    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    monkeypatch.setattr(direct_fetch.requests, "get", lambda url, **kwargs: Response(pages[url]))

    observations = []
    results = direct_fetch.fetch_source(
        {
            "id": "adapter-source",
            "access": "direct_fetch",
            "urls": ["https://example.com/news"],
            "category": "newsroom",
            "article_selector": ".article-card",
            "pagination": {"pages": ["/page/2"]},
            "resolve_article_dates": True,
            "sitemap_fallback": True,
            "max_articles": 3,
        },
        "2026-05-30",
        keywords=["hbm4"],
        observation_sink=observations,
    )

    assert len(results) == 2
    assert results[0].title == "Advanced packaging expands"
    assert results[0].published_at == "2026-05-29"
    assert results[0].query_dimension == "weak_signal"
    assert results[1].url == "https://example.com/news/hbm4-roadmap"
    assert results[1].published_at == "2026-05-28"
    assert results[1].query_id == "df-adapter-source-sitemap"
    assert observations[0]["title"] == "Advanced packaging expands"
    assert observations[0]["parser"] == "direct_fetch"
    assert observations[1]["parser"] == "direct_fetch_sitemap"
    assert "status" not in observations[0]
    assert "score" not in observations[0]


def test_browser_direct_fetch_fallback_preserves_observations(monkeypatch):
    from stratum.sourcing.watchlist import url_channel
    from stratum.sourcing.discovery import SearchResult

    def fake_fetch_source(source, run_date, keywords=None, observation_sink=None, candidate_sink=None, **kwargs):
        result = SearchResult(
            url="https://example.com/news/hbm4",
            title="Fallback HBM4 story",
            snippet="HBM4 update",
            locale="en",
            source_domain="example.com",
            source_type_hint="official",
            engine="direct_fetch:browser-source",
            query_id="df-browser-source",
        )
        if observation_sink is not None:
            observation_sink.append({
                "source": "browser-source",
                "access": "direct_fetch",
                "url": result.url,
                "title": result.title,
                "snippet": result.snippet,
                "published_at": result.published_at,
                "locale": result.locale,
                "source_domain": result.source_domain,
                "source_type_hint": result.source_type_hint,
                "engine": result.engine,
                "query_id": result.query_id,
                "parser": "direct_fetch",
                "observed_at": "2026-05-30T00:00:00+00:00",
            })
        return [result]

    monkeypatch.setattr("stratum.sourcing.watchlist.direct_fetch.fetch_source", fake_fetch_source)

    outcome = url_channel._direct_fetch_fallback(
        {
            "id": "browser-source",
            "access": "browser",
            "locale": "en",
            "category": "newsroom",
        },
        "2026-05-30",
        RuntimeError("browser unavailable"),
        keywords=["hbm4"],
    )

    assert outcome.access == "browser"
    assert outcome.results[0].title == "Fallback HBM4 story"
    assert outcome.observations[0]["parser"] == "direct_fetch"
    assert "score" not in outcome.observations[0]


def test_url_and_browser_candidates_use_shared_admission():
    from stratum.sourcing.discovery import SearchResult
    from stratum.sourcing.watchlist.keywords import admit_results_with_candidates

    results = [
        SearchResult(
            url="https://example.com/news/advanced-packaging",
            title="Advanced packaging expands",
            snippet="Chiplet substrate demand grows",
            locale="en",
            source_type_hint="media",
            engine="browser:test",
            query_id="b-test",
        ),
        SearchResult(
            url="https://example.com/lifestyle",
            title="Unrelated smartphone accessory",
            snippet="Retail accessory launch",
            locale="en",
            source_type_hint="media",
            engine="direct_fetch:test",
            query_id="df-test",
        ),
    ]

    admitted, candidates = admit_results_with_candidates(results, ["hbm4"], source_id="source", access="browser")

    assert [item.title for item in admitted] == ["Advanced packaging expands"]
    assert admitted[0].query_dimension == "weak_signal"
    assert [candidate["status"] for candidate in candidates] == ["weak_signal", "reject"]
    assert candidates[1]["accepted"] is False


def test_direct_fetch_discards_implausible_future_dates():
    from stratum.sourcing.watchlist.direct_fetch import _is_future_date

    assert _is_future_date("2026-06-24", "2026-05-30")
    assert not _is_future_date("2026-05-31", "2026-05-30")


def test_direct_fetch_can_raise_when_source_fetch_fails(monkeypatch):
    from stratum.sourcing.watchlist import direct_fetch
    import pytest
    import requests

    def fail_get(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(direct_fetch.requests, "get", fail_get)

    with pytest.raises(RuntimeError, match="timed out"):
        direct_fetch.fetch_source(
            {
                "id": "broken-source",
                "urls": ["https://example.com/newsroom"],
                "locale": "en",
                "category": "newsroom",
            },
            "2026-05-30",
            raise_on_error=True,
        )


def test_collect_with_stats_records_success_empty_and_error(monkeypatch, tmp_path):
    from stratum import watchlist
    from stratum.sourcing.watchlist import direct_fetch
    from stratum.sourcing.discovery import SearchResult

    sources = [
        {"id": "ok-source", "access": "direct_fetch", "locale": "en", "category": "official"},
        {"id": "empty-source", "access": "rss", "locale": "en", "category": "media", "urls": []},
        {"id": "bad-source", "access": "custom_api"},
    ]

    monkeypatch.setattr(watchlist, "get_active_sources", lambda domain, workspace, **kwargs: sources)
    monkeypatch.setattr(watchlist, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(direct_fetch, "fetch_source", lambda source, run_date, **kwargs: [
        SearchResult(
            url="https://example.com/a",
            title="Samsung HBM update",
            snippet="",
            locale="en",
            published_at="2026-05-30",
            source_domain="example.com",
            source_type_hint="official",
            engine="direct_fetch:ok-source",
            query_id="ok-source",
        )
    ])

    run = watchlist.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert len(run.results) == 1
    by_source = {s.source: s for s in run.source_stats}
    assert by_source["ok-source"].status == "ok"
    assert by_source["ok-source"].hits == 1
    assert by_source["ok-source"].dated == 1
    assert by_source["empty-source"].status == "empty"
    assert by_source["bad-source"].access == "unknown"
    assert by_source["bad-source"].status == "unsupported"


def test_collect_with_stats_dispatches_by_acquisition_channel(monkeypatch, tmp_path):
    import stratum.sourcing.watchlist as watchlist
    from stratum.sourcing.watchlist.models import WatchlistChannelResult
    from stratum.sourcing.discovery import SearchResult

    monkeypatch.setattr(watchlist, "get_active_sources", lambda *args, **kwargs: [
        {"id": "rss-source", "access": "rss", "locale": "en", "category": "media"},
        {"id": "url-source", "access": "direct_fetch", "locale": "en", "category": "official"},
    ])
    monkeypatch.setattr(watchlist, "load_keywords", lambda *args, **kwargs: ["HBM"])

    calls = []

    def fake_rss(source, keywords):
        calls.append(("rss", source["id"], keywords))
        return WatchlistChannelResult(
            results=[
                SearchResult(
                    url="https://rss.example.com/a",
                    title="RSS HBM",
                    snippet="",
                    locale="en",
                    engine="rss:rss-source",
                    query_id="rss-rss-source",
                )
            ],
            access="rss",
            status="ok",
            locale="en",
            category="media",
        )

    def fake_url(source, run_date):
        calls.append(("url", source["id"], run_date))
        return WatchlistChannelResult(
            results=[],
            access="direct_fetch",
            status="empty",
            locale="en",
            category="official",
        )

    monkeypatch.setattr("stratum.sourcing.watchlist.rss_channel.collect_source", fake_rss)
    monkeypatch.setattr("stratum.sourcing.watchlist.url_channel.collect_source", fake_url)

    run = watchlist.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert calls == [
        ("rss", "rss-source", ["HBM"]),
        ("url", "url-source", "2026-05-30"),
    ]
    assert len(run.results) == 1
    assert [stat.access for stat in run.source_stats] == ["rss", "direct_fetch"]


def test_collect_with_stats_marks_direct_fetch_failure_as_error(monkeypatch, tmp_path):
    from stratum import watchlist
    from stratum.sourcing.watchlist import direct_fetch

    sources = [
        {
            "id": "broken-source",
            "access": "direct_fetch",
            "locale": "en",
            "category": "official",
            "urls": ["https://example.com/newsroom"],
        }
    ]

    def fail(source, run_date, **kwargs):
        assert kwargs["raise_on_error"] is True
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(watchlist, "get_active_sources", lambda domain, workspace, **kwargs: sources)
    monkeypatch.setattr(watchlist, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(direct_fetch, "fetch_source", fail)

    run = watchlist.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert run.results == []
    stat = run.source_stats[0]
    assert stat.source == "broken-source"
    assert stat.access == "direct_fetch"
    assert stat.status == "error"
    assert stat.hits == 0
    assert stat.error == "HTTP 500"


def test_collect_with_stats_marks_rss_fetch_failure_as_error(monkeypatch, tmp_path):
    from stratum import watchlist
    from stratum.sourcing.watchlist import rss

    sources = [
        {
            "id": "broken-feed",
            "access": "rss",
            "locale": "en",
            "category": "media",
            "urls": ["https://example.com/feed.xml"],
        }
    ]

    def fail(url, keywords, source_id, locale, category, timeout, **kwargs):
        assert kwargs["raise_on_error"] is True
        raise RuntimeError("feed timeout")

    monkeypatch.setattr(watchlist, "get_active_sources", lambda domain, workspace, **kwargs: sources)
    monkeypatch.setattr(watchlist, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(rss, "fetch_feed", fail)

    run = watchlist.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert run.results == []
    stat = run.source_stats[0]
    assert stat.source == "broken-feed"
    assert stat.access == "rss"
    assert stat.status == "error"
    assert stat.hits == 0
    assert stat.error == "https://example.com/feed.xml: feed timeout"


def test_collect_with_stats_keeps_rss_results_when_one_feed_url_fails(monkeypatch, tmp_path):
    from stratum import watchlist
    from stratum.sourcing.watchlist import rss
    from stratum.sourcing.discovery import SearchResult

    sources = [
        {
            "id": "mixed-feed",
            "access": "rss",
            "locale": "en",
            "category": "media",
            "urls": ["https://example.com/broken.xml", "https://example.com/good.xml"],
        }
    ]

    def fetch(url, keywords, source_id, locale, category, timeout, **kwargs):
        assert kwargs["raise_on_error"] is True
        if "broken" in url:
            raise RuntimeError("feed timeout")
        return [
            SearchResult(
                url="https://example.com/story",
                title="Samsung HBM4 update",
                snippet="",
                locale=locale,
                source_domain="example.com",
                source_type_hint="media",
                engine=f"rss:{source_id}",
                query_id=f"rss-{source_id}",
            )
        ]

    monkeypatch.setattr(watchlist, "get_active_sources", lambda domain, workspace, **kwargs: sources)
    monkeypatch.setattr(watchlist, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(rss, "fetch_feed", fetch)

    run = watchlist.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert len(run.results) == 1
    stat = run.source_stats[0]
    assert stat.source == "mixed-feed"
    assert stat.status == "ok"
    assert stat.hits == 1
    assert "broken.xml: feed timeout" in stat.error


def test_collect_with_stats_marks_missing_browser_runtime_as_unsupported(monkeypatch, tmp_path):
    from stratum import watchlist
    from stratum.sourcing.watchlist import browser

    sources = [
        {
            "id": "js-newsroom",
            "access": "browser",
            "locale": "en",
            "category": "newsroom",
            "urls": ["https://example.com/newsroom"],
        }
    ]

    def unavailable(source, run_date):
        raise browser.BrowserWatchlistUnavailable("Playwright missing")

    monkeypatch.setattr(watchlist, "get_active_sources", lambda domain, workspace, **kwargs: sources)
    monkeypatch.setattr(watchlist, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(browser, "fetch_source", unavailable)

    run = watchlist.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert run.results == []
    assert len(run.source_stats) == 1
    stat = run.source_stats[0]
    assert stat.source == "js-newsroom"
    assert stat.access == "browser"
    assert stat.status == "unsupported"
    assert stat.hits == 0
    assert "Playwright missing" in stat.error


def test_collect_with_stats_uses_configured_browser_static_fallback(monkeypatch, tmp_path):
    from stratum import watchlist
    from stratum.sourcing.watchlist import browser, direct_fetch
    from stratum.sourcing.discovery import SearchResult

    sources = [
        {
            "id": "js-newsroom",
            "access": "browser",
            "fallback_access": "direct_fetch",
            "locale": "en",
            "category": "newsroom",
            "urls": ["https://example.com/newsroom"],
        }
    ]

    def unavailable(source, run_date):
        raise browser.BrowserWatchlistUnavailable("Playwright missing")

    def fallback(source, run_date, **kwargs):
        assert source["access"] == "direct_fetch"
        assert kwargs["raise_on_error"] is True
        return [
            SearchResult(
                url="https://example.com/news/hbm4",
                title="Samsung HBM4 newsroom update",
                snippet="",
                locale="en",
                published_at="2026-05-30",
                source_domain="example.com",
                source_type_hint="official",
                engine="direct_fetch:js-newsroom",
                query_id="js-newsroom",
            )
        ]

    monkeypatch.setattr(watchlist, "get_active_sources", lambda domain, workspace, **kwargs: sources)
    monkeypatch.setattr(watchlist, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(browser, "fetch_source", unavailable)
    monkeypatch.setattr(direct_fetch, "fetch_source", fallback)

    run = watchlist.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert len(run.results) == 1
    stat = run.source_stats[0]
    assert stat.source == "js-newsroom"
    assert stat.access == "browser"
    assert stat.status == "ok"
    assert stat.hits == 1
    assert stat.dated == 1
    assert "direct_fetch fallback" in stat.error
