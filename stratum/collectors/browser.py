"""Browser collector — headless Chrome via Playwright.

For JS-rendered pages where direct_fetch (requests + HTML parse) fails.
Uses Playwright's Chromium to render the page, then applies the same
article extraction logic as direct_fetch.

Reads active sources with access=browser from domain.yaml's source_registry.
Interface: fetch_source(source, run_date) → list[SearchResult].
"""

import re
import sys
from importlib.util import find_spec
from typing import Optional
from urllib.parse import urljoin

from stratum.collectors.common import extract_domain, normalize_source_type
from stratum.collectors.direct_fetch import (
    _ArticleExtractor,
    _extract_date,
    _extract_read_more_links,
    _is_article_url,
)
from stratum.subsystems.search.models import SearchResult

# ── Playwright import (lazy — only on first use) ──
_playwright = None


class BrowserCollectorUnavailable(RuntimeError):
    """Raised when browser collection is configured but Playwright is unavailable."""


def ensure_browser_available() -> None:
    """Fail with an actionable message before browser sources are silently skipped."""
    if find_spec("playwright") is None:
        raise BrowserCollectorUnavailable(
            "Playwright is required for access=browser sources. "
            "Install the browser extra and browsers: pip install -e '.[browser]' && playwright install chromium"
        )


def _get_playwright():
    global _playwright
    ensure_browser_available()
    if _playwright is None:
        from playwright.sync_api import sync_playwright
        _playwright = sync_playwright().start()
    return _playwright


def _trim_title(title: str) -> Optional[str]:
    """Reject boilerplate / empty titles."""
    title = re.sub(r'\s+', ' ', title).strip()
    if not title or len(title) < 10:
        return None
    lower = title.lower()
    if lower in ('read article', 'learn more', 'read more', 'click here',
                 'read', 'press releases', 'newsroom', 'news', 'blog'):
        return None
    if len(title.split()) <= 2 and title == title.upper():
        return None
    return title


def _extract_from_snapshot(page, base_url: str, max_articles: int) -> list[dict]:
    """Extract article links from Playwright page — heading-first.

    Playwright-rendered DOM → _ArticleExtractor HTML parser.
    Returns list of {url, title, in_heading}.
    """
    html = page.content()
    parser = _ArticleExtractor(base_url)
    parser.feed(html)
    return parser.links[:max_articles]


def _convert_links(links: list[dict], source_id: str, source_domain: str,
                   locale: str, category: str, html: str,
                   seen_urls: set, max_articles: int) -> list[SearchResult]:
    """Convert extracted link dicts → SearchResult objects."""
    results = []
    for link in links:
        if len(results) >= max_articles:
            break

        link_url = link['url']
        if link_url in seen_urls:
            continue

        title = _trim_title(link.get('title', ''))
        if not title:
            continue

        published_at = _extract_date(link_url, html)
        results.append(SearchResult(
            url=link_url,
            title=title,
            snippet=title,
            locale=locale,
            published_at=published_at,
            source_domain=extract_domain(link_url),
            source_type_hint=normalize_source_type(category),
            engine=f"browser:{source_id}",
            query_id=f"b-{source_id}",
        ))
        seen_urls.add(link_url)

    return results


def _extract_list_links(page, base_url: str, source_domain: str,
                        seen_urls: set, max_articles: int) -> list[dict]:
    """Extract article links from JS-rendered DOM via Playwright evaluate().

    For pages where article titles are in bare <a> tags inside <li>/<div>
    (Samsung newsroom, tech-blog, Kioxia newsroom). Uses page.evaluate()
    for native DOM access — avoids regex complexity with large HTML.

    Strategy:
    1. JS scans all <a href> with article-like URL patterns
    2. For each, finds parent <li> and extracts <time> date
    3. Returns [{url, title, date}]
    """
    js_code = r"""
    () => {
        const results = [];
        const seen = new Set();
        const articlePattern = /\/(?:news|press|blog|article|story|fact|tech-blog|insights)\//i;
        const navPattern = /\/(?:category|tag|author|page)\//i;
        const skipTexts = new Set([
            'read article', 'read more', 'learn more', 'click here',
            'read', 'press releases', 'newsroom', 'news', 'blog', 'home',
            'trending posts', 'popular news', 'search', 'view more'
        ]);

        const links = document.querySelectorAll('a[href]');
        for (const a of links) {
            if (results.length >= %d * 2) break;

            const href = a.getAttribute('href');
            if (!href || href.startsWith('#') || href.startsWith('javascript:')) continue;

            // Absolute URL
            let fullUrl = href;
            if (!href.startsWith('http')) {
                try { fullUrl = new URL(href, window.location.href).href; }
                catch(e) { continue; }
            }

            if (!articlePattern.test(fullUrl)) continue;
            if (navPattern.test(fullUrl)) continue;

            // Title: visible text, strip category prefix like "Tech Blog"
            let title = a.textContent.replace(/\\s+/g, ' ').trim();
            // Remove common category prefixes
            title = title.replace(/^(Tech Blog|News|Press Release|Blog|Insights)\\s*/i, '').trim();
            if (title.length < 10 || title.length > 200) continue;
            if (skipTexts.has(title.toLowerCase())) continue;

            // Find <time> in parent <li>, container, or sibling
            const li = a.closest('li');
            let container = li || a.parentElement;
            let timeEl = container ? container.querySelector('time') : null;
            // If not found, check next sibling (hero/featured layouts)
            if (!timeEl && container && container.nextElementSibling) {
                timeEl = container.nextElementSibling.querySelector('time');
            }
            const date = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';

            results.push({url: fullUrl, title: title, date: date});
        }
        return results;
    }
    """ % (max_articles * 2)

    try:
        raw = page.evaluate(js_code)
    except Exception as e:
        print(f"  ⚠️  browser JS eval error: {e}", file=sys.stderr)
        return []

    results = []
    for item in raw:
        url = item.get('url', '')
        if url in seen_urls:
            continue
        results.append({
            'url': url,
            'title': item.get('title', ''),
            'date': item.get('date', ''),
        })
        seen_urls.add(url)

    return results[:max_articles]


def fetch_source(source: dict, run_date: str, timeout: int = 30) -> list[SearchResult]:
    """Fetch articles from a single browser-collected source.

    Args:
        source: Source dict from domain.yaml source_registry
        run_date: YYYY-MM-DD for freshness filtering (unused — verify stage handles)
        timeout: page load timeout in seconds

    Returns:
        List of SearchResult (may be empty on failure)
    """
    ensure_browser_available()
    results = []
    source_id = source.get("id", "unknown")
    locale = source.get("locale", "en")
    category = source.get("category", "media")
    urls = source.get("urls", [])
    max_articles = source.get("max_articles", source.get("defaults", {}).get("max_articles_per_url", 5))

    pw = _get_playwright()
    browser = None

    try:
        browser = pw.chromium.launch(headless=True)

        for url in urls:
            try:
                context = browser.new_context(
                    user_agent="Stratum/1.0 (storage industry monitor; +https://github.com/stratum)",
                    locale="en-US",
                )
                page = context.new_page()
                page.set_default_timeout(timeout * 1000)
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(1000)  # extra grace for late JS

                # Parse
                domain = extract_domain(url)
                html = page.content()
                links = _extract_from_snapshot(page, url, max_articles * 2)

                seen_urls: set[str] = set()

                # Phase 1: heading-first
                heading_links = [l for l in links if l.get('in_heading')]
                if heading_links:
                    results.extend(_convert_links(
                        heading_links, source_id, domain, locale, category,
                        html, seen_urls, max_articles,
                    ))

                # Phase 2: read-more fallback
                remaining = max_articles - len(results)
                if remaining > 0:
                    fallback = _extract_read_more_links(
                        html, url, domain, locale, category, source_id,
                        remaining, seen_urls,
                    )
                    results.extend(fallback)

                # Phase 3: link-list extraction (li>a + time pattern)
                remaining = max_articles - len(results)
                if remaining > 0:
                    list_items = _extract_list_links(
                        page, url, domain, seen_urls, remaining,
                    )
                    for item in list_items:
                        published_at = item.get('date') or None
                        # Normalise date strings like "May 20, 2026" → YYYY-MM-DD
                        if published_at and not re.match(r'\d{4}-\d{2}-\d{2}', published_at):
                            published_at = _extract_date(item['url'], html)
                            if not published_at and item.get('date'):
                                published_at = _extract_date(item['url'], item['date'])
                        results.append(SearchResult(
                            url=item['url'],
                            title=item['title'],
                            snippet=item['title'],
                            locale=locale,
                            published_at=published_at,
                            source_domain=extract_domain(item['url']),
                            source_type_hint=normalize_source_type(category),
                            engine=f"browser:{source_id}",
                            query_id=f"b-{source_id}-list",
                        ))

                context.close()

            except Exception as e:
                print(f"  ⚠️  browser [{source_id}] [{url}]: {e}", file=sys.stderr)

    except Exception as e:
        print(f"  ⚠️  browser [{source_id}] launch error: {e}", file=sys.stderr)
    finally:
        if browser:
            browser.close()

    return results


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Collect articles from all active browser sources.

    Args:
        domain: Domain ID (e.g. 'storage')
        workspace: Project root path
        run_date: YYYY-MM-DD

    Returns:
        Combined list of SearchResult from all sources
    """
    from stratum.collectors.registry import get_active_sources

    sources = get_active_sources(domain, workspace, access="browser")
    if not sources:
        print("  ℹ️  No active browser sources", file=sys.stderr)
        return []

    all_results = []
    for source in sources:
        sid = source.get("id", "?")
        results = fetch_source(source, run_date)
        if results:
            print(f"  ✅ browser [{sid}]: {len(results)} articles", file=sys.stderr)
        else:
            print(f"  ⚠️  browser [{sid}]: no articles", file=sys.stderr)
        all_results.extend(results)

    return all_results
