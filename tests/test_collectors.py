"""Collector unit tests."""


def test_atom_feed_parses_namespaced_empty_link():
    from stratum.collectors.rss import _parse_atom_feed

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
    from stratum.collectors.rss import _parse_rss_date

    assert _parse_rss_date("2026-05-30T12:00:00+09:00") == "2026-05-30"
    assert _parse_rss_date("Thu, 28 May 2026 15:02:21 GMT") == "2026-05-28"


def test_collector_common_normalizes_source_identity():
    from stratum.collectors.common import extract_domain, normalize_source_type

    assert extract_domain("https://www.micron.com/about/press/news") == "micron.com"
    assert extract_domain("https://m.reuters.com/technology") == "reuters.com"
    assert extract_domain("https://ww2.example.com/news") == "ww2.example.com"
    assert normalize_source_type("newsroom") == "official"
    assert normalize_source_type("rss") == "media"
    assert normalize_source_type("blog") == "blog"
    assert normalize_source_type("vendor_portal") == "unknown"


def test_rss_uses_article_domain_and_canonical_source_type(monkeypatch):
    from stratum.collectors import rss

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
    from stratum.collectors import rss
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
    from stratum.collectors.keywords import load_keywords, match_keywords

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


def test_source_registry_applies_access_defaults(tmp_path):
    from stratum.collectors.registry import get_active_sources

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


def test_direct_fetch_uses_article_page_date_not_list_page_date(monkeypatch):
    from stratum.collectors import direct_fetch

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


def test_direct_fetch_discards_implausible_future_dates():
    from stratum.collectors.direct_fetch import _is_future_date

    assert _is_future_date("2026-06-24", "2026-05-30")
    assert not _is_future_date("2026-05-31", "2026-05-30")


def test_direct_fetch_can_raise_when_source_fetch_fails(monkeypatch):
    from stratum.collectors import direct_fetch
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
    from stratum import collectors
    from stratum.collectors import direct_fetch
    from stratum.subsystems.search.models import SearchResult

    sources = [
        {"id": "ok-source", "access": "direct_fetch", "locale": "en", "category": "official"},
        {"id": "empty-source", "access": "rss", "locale": "en", "category": "media", "urls": []},
        {"id": "bad-source", "access": "custom_api"},
    ]

    monkeypatch.setattr(collectors, "get_active_sources", lambda domain, workspace: sources)
    monkeypatch.setattr(collectors, "load_keywords", lambda domain, workspace: ["hbm"])
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

    run = collectors.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert len(run.results) == 1
    by_source = {s.source: s for s in run.source_stats}
    assert by_source["ok-source"].status == "ok"
    assert by_source["ok-source"].hits == 1
    assert by_source["ok-source"].dated == 1
    assert by_source["empty-source"].status == "empty"
    assert by_source["bad-source"].access == "unknown"
    assert by_source["bad-source"].status == "unsupported"


def test_collect_with_stats_marks_direct_fetch_failure_as_error(monkeypatch, tmp_path):
    from stratum import collectors
    from stratum.collectors import direct_fetch

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

    monkeypatch.setattr(collectors, "get_active_sources", lambda domain, workspace: sources)
    monkeypatch.setattr(collectors, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(direct_fetch, "fetch_source", fail)

    run = collectors.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert run.results == []
    stat = run.source_stats[0]
    assert stat.source == "broken-source"
    assert stat.access == "direct_fetch"
    assert stat.status == "error"
    assert stat.hits == 0
    assert stat.error == "HTTP 500"


def test_collect_with_stats_marks_rss_fetch_failure_as_error(monkeypatch, tmp_path):
    from stratum import collectors
    from stratum.collectors import rss

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

    monkeypatch.setattr(collectors, "get_active_sources", lambda domain, workspace: sources)
    monkeypatch.setattr(collectors, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(rss, "fetch_feed", fail)

    run = collectors.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert run.results == []
    stat = run.source_stats[0]
    assert stat.source == "broken-feed"
    assert stat.access == "rss"
    assert stat.status == "error"
    assert stat.hits == 0
    assert stat.error == "https://example.com/feed.xml: feed timeout"


def test_collect_with_stats_keeps_rss_results_when_one_feed_url_fails(monkeypatch, tmp_path):
    from stratum import collectors
    from stratum.collectors import rss
    from stratum.subsystems.search.models import SearchResult

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

    monkeypatch.setattr(collectors, "get_active_sources", lambda domain, workspace: sources)
    monkeypatch.setattr(collectors, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(rss, "fetch_feed", fetch)

    run = collectors.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert len(run.results) == 1
    stat = run.source_stats[0]
    assert stat.source == "mixed-feed"
    assert stat.status == "ok"
    assert stat.hits == 1
    assert "broken.xml: feed timeout" in stat.error


def test_collect_with_stats_marks_missing_browser_runtime_as_unsupported(monkeypatch, tmp_path):
    from stratum import collectors
    from stratum.collectors import browser

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
        raise browser.BrowserCollectorUnavailable("Playwright missing")

    monkeypatch.setattr(collectors, "get_active_sources", lambda domain, workspace: sources)
    monkeypatch.setattr(collectors, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(browser, "fetch_source", unavailable)

    run = collectors.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert run.results == []
    assert len(run.source_stats) == 1
    stat = run.source_stats[0]
    assert stat.source == "js-newsroom"
    assert stat.access == "browser"
    assert stat.status == "unsupported"
    assert stat.hits == 0
    assert "Playwright missing" in stat.error


def test_collect_with_stats_uses_configured_browser_static_fallback(monkeypatch, tmp_path):
    from stratum import collectors
    from stratum.collectors import browser, direct_fetch
    from stratum.subsystems.search.models import SearchResult

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
        raise browser.BrowserCollectorUnavailable("Playwright missing")

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

    monkeypatch.setattr(collectors, "get_active_sources", lambda domain, workspace: sources)
    monkeypatch.setattr(collectors, "load_keywords", lambda domain, workspace: ["hbm"])
    monkeypatch.setattr(browser, "fetch_source", unavailable)
    monkeypatch.setattr(direct_fetch, "fetch_source", fallback)

    run = collectors.collect_with_stats("storage", str(tmp_path), "2026-05-30")

    assert len(run.results) == 1
    stat = run.source_stats[0]
    assert stat.source == "js-newsroom"
    assert stat.access == "browser"
    assert stat.status == "ok"
    assert stat.hits == 1
    assert stat.dated == 1
    assert "direct_fetch fallback" in stat.error
