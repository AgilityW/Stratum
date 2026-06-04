"""Direct fetch watchlist — HTTP GET newsroom pages, parse article links.

Reads active sources with access=direct_fetch from domain.yaml's source_registry.
For each source URL, fetches the page, extracts article links and metadata,
and returns normalized SearchResult objects.

HTML parsing uses stdlib html.parser + regex for date extraction.
No external dependencies required.
"""

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

from stratum.sourcing.watchlist.common import extract_domain, normalize_source_type
from stratum.sourcing.watchlist.keywords import admit_results_with_candidates
from stratum.sourcing.watchlist.observations import observation_from_result
from stratum.sourcing.discovery import SearchResult


# ── Date extraction patterns ──
# ISO dates in URLs and text: 2026-05-30, 2026/05/30
_DATE_IN_URL = re.compile(r'/(\d{4})[/-](\d{2})[/-](\d{2})[/-]')
# Text dates in English or CJK numeric date formats.
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may_short": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_TEXT_DATE = re.compile(
    r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*)\s+(\d{1,2}),?\s+(\d{4})',
    re.IGNORECASE,
)
_CN_DATE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')

# URL patterns that look like article pages
_ARTICLE_URL_PATTERNS = [
    r'/news-release', r'/press-release', r'/news/', r'/press/',
    r'/blog/', r'/article/', r'/story/', r'/fact/',
    r'/\d{4}/\d{2}/',  # WordPress date URLs
    r'/news-releases/', r'/post/',
    r'/insights/',  # Kioxia insights/articles
]


def _is_article_url(url: str, in_heading: bool = False) -> bool:
    """Check if a URL looks like an article/news page (not category/index).
    
    Heading links are more permissive — they're almost always articles.
    """
    url_lower = url.lower()
    
    # Skip obvious non-article patterns
    skip_patterns = ['/category/', '/tag/', '/author/', '/page/', 'wp-content', '.jpg', '.png', '.pdf']
    for pat in skip_patterns:
        if pat in url_lower:
            return False
    
    # Heading links: accept if URL has a non-trivial slug
    if in_heading:
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        if not path:
            return False
        segments = path.split('/')
        # Reject single-segment flat paths (/products, /about, /partners)
        if len(segments) == 1:
            slug = segments[0]
            # Accept if slug looks like an article (has hyphens, numbers, or is long)
            if '-' in slug or re.search(r'\d', slug) or len(slug) > 20:
                return True
            return False
        # Multi-segment: accept if not a category/tag page
        return True
    
    # Plain links: require recognisable article patterns
    for pat in _ARTICLE_URL_PATTERNS:
        if re.search(pat, url_lower):
            return True
    # Also check for date segments in path
    if _DATE_IN_URL.search(url):
        return True
    return False


def _extract_date(url: str, text: str) -> Optional[str]:
    """Extract date from URL path or surrounding text. Returns YYYY-MM-DD or None."""
    # Try URL first (most reliable)
    m = _DATE_IN_URL.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    
    # Try text date
    m = _TEXT_DATE.search(text)
    if m:
        month = _MONTHS.get(m.group(1).lower(), 1)
        day = int(m.group(2))
        year = int(m.group(3))
        return f"{year}-{month:02d}-{day:02d}"
    
    # Try Chinese date
    m = _CN_DATE.search(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    
    return None


def _is_future_date(date_str: Optional[str], run_date: str, grace_days: int = 1) -> bool:
    """Return True when a candidate publication date is implausibly after run_date."""
    if not date_str:
        return False
    try:
        candidate = datetime.fromisoformat(date_str).date()
        current = datetime.fromisoformat(run_date).date()
    except ValueError:
        return False
    return (candidate - current).days > grace_days


def _clean_text(text: str) -> str:
    """Normalize extracted HTML text."""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', unescape(text)).strip()


_ARTICLE_DATE_PATTERNS = [
    r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+name=["\']publish_date["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']',
    r'<time[^>]+datetime=["\']([^"\']+)["\']',
    r'"datePublished"\s*:\s*"([^"]+)"',
]


def _normalise_date_candidate(value: str) -> Optional[str]:
    """Normalize common article-page date strings to YYYY-MM-DD."""
    value = unescape(value or "").strip()
    if not value:
        return None
    iso = value[:10]
    if re.match(r'\d{4}-\d{2}-\d{2}', iso):
        return iso
    return _extract_date("", value)


def _extract_article_page_date(html: str) -> Optional[str]:
    """Extract publication date from article detail HTML."""
    for pattern in _ARTICLE_DATE_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            parsed = _normalise_date_candidate(match.group(1))
            if parsed:
                return parsed
    return _extract_date("", html)


def _fetch_article_date(url: str, headers: dict, timeout: int) -> Optional[str]:
    """Fetch an article detail page and extract its publication date."""
    resp = requests.get(url, headers=headers, timeout=min(timeout, 3), allow_redirects=True)
    resp.raise_for_status()
    return _extract_article_page_date(resp.text)


def _expand_urls(source: dict) -> list[str]:
    """Expand configured URLs with optional pagination settings."""
    urls = list(source.get("urls", []) or [])
    pagination = source.get("pagination") or {}
    if not isinstance(pagination, dict):
        return urls
    pages = pagination.get("pages") or []
    for base_url in list(urls):
        for page in pages:
            urls.append(urljoin(base_url, str(page)))
        path_format = pagination.get("path_format")
        max_pages = int(pagination.get("max_pages") or 0)
        if path_format and max_pages > 1:
            for page_num in range(2, max_pages + 1):
                urls.append(urljoin(base_url, str(path_format).format(page=page_num)))
    return list(dict.fromkeys(urls))


def _selector_pattern(selector: str) -> re.Pattern | None:
    """Compile a small CSS-selector subset for source adapters."""
    selector = str(selector or "").strip()
    if not selector:
        return None
    class_match = re.search(r'\.([A-Za-z0-9_-]+)', selector)
    if class_match:
        cls = re.escape(class_match.group(1))
        return re.compile(
            rf'<a[^>]+class=["\'][^"\']*{cls}[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
    return None


def _extract_selector_links(html: str, base_url: str, selector: str) -> list[dict]:
    pattern = _selector_pattern(selector)
    if not pattern:
        return []
    links = []
    for href, text in pattern.findall(html):
        title = _clean_text(text)
        if title:
            links.append({"url": urljoin(base_url, href), "title": title})
    return links


def _sitemap_urls(source: dict, base_url: str) -> list[str]:
    configured = source.get("sitemap_urls") or []
    if configured:
        return list(configured)
    parsed = urlparse(base_url)
    return [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]


def _fetch_sitemap_candidates(source: dict, headers: dict, timeout: int, max_articles: int) -> list[dict]:
    candidates: list[dict] = []
    seen_sitemaps: set[str] = set()

    def parse_sitemap(sitemap_url: str) -> bool:
        if sitemap_url in seen_sitemaps:
            return False
        seen_sitemaps.add(sitemap_url)
        try:
            resp = requests.get(sitemap_url, headers=headers, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
        except requests.RequestException:
            return False

        nested = re.findall(r'<sitemap>\s*.*?<loc>\s*([^<]+)\s*</loc>.*?</sitemap>', resp.text, re.IGNORECASE | re.DOTALL)
        for nested_url in nested[:10]:
            if len(candidates) >= max_articles:
                return True
            parse_sitemap(unescape(nested_url).strip())

        for url_block in re.findall(r'<url>\s*(.*?)\s*</url>', resp.text, re.IGNORECASE | re.DOTALL):
            loc_match = re.search(r'<loc>\s*([^<]+)\s*</loc>', url_block, re.IGNORECASE)
            if not loc_match:
                continue
            loc = unescape(loc_match.group(1)).strip()
            if not _is_article_url(loc):
                continue
            lastmod_match = re.search(r'<lastmod>\s*([^<]+)\s*</lastmod>', url_block, re.IGNORECASE)
            lastmod = _normalise_date_candidate(lastmod_match.group(1)) if lastmod_match else None
            title = loc.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").strip()
            candidates.append({
                "url": loc,
                "title": title or loc,
                "published_at": lastmod,
            })
            if len(candidates) >= max_articles:
                return True
        return bool(candidates)

    for base_url in source.get("urls", []) or []:
        for sitemap_url in _sitemap_urls(source, base_url):
            parse_sitemap(sitemap_url)
            if len(candidates) >= max_articles:
                return candidates
    return candidates


def _resolve_published_at(url: str, run_date: str, headers: dict, timeout: int,
                          fallback_text: str = "") -> Optional[str]:
    """Resolve publication date without using unrelated list-page dates."""
    date = _extract_date(url, "")
    if date and not _is_future_date(date, run_date):
        return date

    try:
        date = _fetch_article_date(url, headers, timeout)
        if date and not _is_future_date(date, run_date):
            return date
    except requests.RequestException:
        pass

    date = _extract_date("", fallback_text)
    if date and not _is_future_date(date, run_date):
        return date
    return None


def _resolve_published_dates(urls: list[str], run_date: str, headers: dict,
                             timeout: int) -> dict[str, Optional[str]]:
    """Resolve article dates concurrently so direct_fetch stays responsive."""
    unique_urls = list(dict.fromkeys(urls))
    if not unique_urls:
        return {}

    date_map: dict[str, Optional[str]] = {}
    max_workers = min(5, len(unique_urls))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_resolve_published_at, url, run_date, headers, timeout): url
            for url in unique_urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                date_map[url] = future.result()
            except Exception:
                date_map[url] = None
    return date_map


class _ArticleExtractor(HTMLParser):
    """Extract article links from HTML using heading-first strategy.
    
    Strategy:
    1. Find <a> inside <h2>/<h3>/<h4> — these are article title links
    2. Fall back to standalone <a> if no heading links found
    3. Filter out category/navigation pages
    """
    
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[dict] = []  # [{url, title}]
        self._in_heading: Optional[str] = None  # h2/h3/h4
        self._in_link: bool = False
        self._link_href: str = ""
        self._link_text: list[str] = []
    
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag in ('h2', 'h3', 'h4'):
            self._in_heading = tag
        
        if tag == 'a':
            self._in_link = True
            self._link_href = attrs_dict.get('href', '')
            self._link_text = []
    
    def handle_data(self, data):
        if self._in_link:
            self._link_text.append(data.strip())
    
    def handle_endtag(self, tag):
        if tag == 'a' and self._in_link:
            href = self._link_href
            title = _clean_text(' '.join(t for t in self._link_text if t))
            
            if href and not href.startswith('#') and not href.startswith('javascript:'):
                full_url = urljoin(self.base_url, href)
                if title and _is_article_url(full_url, self._in_heading is not None):
                    is_heading = self._in_heading is not None
                    self.links.append({
                        'url': full_url,
                        'title': title,
                        'in_heading': is_heading,
                    })
            
            self._in_link = False
            self._link_href = ""
            self._link_text = []
        
        if tag == self._in_heading:
            self._in_heading = None


def _extract_read_more_links(html: str, base_url: str, domain: str, locale: str,
                              category: str, source_id: str, max_results: int,
                              seen_urls: set, run_date: str = "",
                              headers: Optional[dict] = None,
                              timeout: int = 15) -> list[SearchResult]:
    """Extract articles from 'Read article' style links by looking backward for headings.
    
    Used as fallback when heading-first extraction doesn't capture all articles
    (common on AEM and corporate CMS sites where article titles are in separate
    elements from the read-more button).
    """
    results = []
    
    # Match: <a href="...">Read article</a>, <a href="...">Read More</a>, <a href="...">Learn More</a>
    pattern = re.compile(
        r'<a[^>]*href="([^"]*)"[^>]*>\s*(Read article|Read [Mm]ore|Learn [Mm]ore|READ)\s*</a>',
        re.IGNORECASE,
    )
    
    for m in pattern.finditer(html):
        if len(results) >= max_results:
            break
        
        href = m.group(1)
        full_url = urljoin(base_url, href)
        
        if full_url in seen_urls or not _is_article_url(full_url):
            continue
        
        # Look backward up to 2000 chars for nearest heading
        pos = m.start()
        chunk = html[max(0, pos - 2000):pos]
        headings = re.findall(r'<h[2-4][^>]*>(?:<a[^>]*>)?\s*(.+?)\s*(?:</a>)?</h[2-4]>', chunk, re.DOTALL)
        
        if not headings:
            continue
        
        title = _clean_text(headings[-1])
        
        if len(title) < 10:
            continue
        
        if run_date and headers:
            published_at = _resolve_published_at(
                full_url,
                run_date,
                headers,
                timeout,
                fallback_text=chunk,
            )
        else:
            published_at = _extract_date(full_url, chunk)
            if run_date and _is_future_date(published_at, run_date):
                published_at = None
        
        result = SearchResult(
            url=full_url,
            title=title,
            snippet=title,
            locale=locale,
            published_at=published_at,
            source_domain=extract_domain(full_url),
            source_type_hint=normalize_source_type(category),
            engine=f"direct_fetch:{source_id}",
            query_id=f"df-{source_id}-fallback",
        )
        results.append(result)
        seen_urls.add(full_url)
    
    return results


def fetch_source(
    source: dict,
    run_date: str,
    timeout: int = 15,
    raise_on_error: bool = False,
    keywords: list[str] | None = None,
    observation_sink: list[dict] | None = None,
    candidate_sink: list[dict] | None = None,
) -> list[SearchResult]:
    """Fetch articles from a single source definition.
    
    Args:
        source: Source dict from domain.yaml source_registry
        run_date: YYYY-MM-DD for freshness filtering
        timeout: HTTP timeout in seconds
    
    Returns:
        List of SearchResult. When raise_on_error is true, a source whose URLs
        all fail raises instead of looking like a valid empty source.
    """
    results = []
    errors = []
    source_id = source.get("id", "unknown")
    source_name = source.get("name", source_id)
    locale = source.get("locale", "en")
    category = source.get("category", "media")
    urls = _expand_urls(source)
    max_articles = source.get("max_articles", source.get("defaults", {}).get("max_articles_per_url", 10))
    timeout = source.get("timeout", 15)
    resolve_article_dates = bool(source.get("resolve_article_dates", False))
    
    headers = {
        "User-Agent": "Stratum/1.0 (storage industry monitor; +https://github.com/stratum)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            
            # Parse HTML for article links
            parser = _ArticleExtractor(url)
            parser.feed(resp.text)
            
            domain = extract_domain(url)
            source_type = normalize_source_type(category)
            
            # Detect page structure: AEM/corp CMS with "Read article" buttons
            has_read_more = bool(re.search(
                r'<a[^>]*>\s*(Read article|Learn [Mm]ore|READ)\s*</a>',
                resp.text, re.IGNORECASE
            ))
            
            # Phase 1: heading-first links (skip if page has read-more buttons)
            if not has_read_more:
                candidates: list[tuple[str, str]] = []
                adapter_links = _extract_selector_links(
                    resp.text,
                    url,
                    source.get("article_selector") or source.get("list_selector") or "",
                )
                link_pool = adapter_links or parser.links
                for link in link_pool:
                    if len(candidates) >= max_articles:
                        break
                        
                    link_url = link['url']
                    title = link['title']
                    
                    if len(title) < 10 or title.lower() in ('read article', 'learn more', 'read more', 'click here', 'read', 'press releases', 'newsroom'):
                        continue
                    
                    if len(title.split()) <= 2 and title == title.upper():
                        continue

                    candidates.append((link_url, title))

                if resolve_article_dates:
                    dates = _resolve_published_dates(
                        [url for url, _title in candidates],
                        run_date,
                        headers,
                        timeout,
                    )
                else:
                    dates = {
                        url: (
                            date if not _is_future_date(date, run_date) else None
                        )
                        for url, _title in candidates
                        for date in [_extract_date(url, "")]
                    }
                for link_url, title in candidates:
                    published_at = dates.get(link_url)
                    
                    result = SearchResult(
                        url=link_url,
                        title=title,
                        snippet=title,
                        locale=locale,
                        published_at=published_at,
                        source_domain=extract_domain(link_url),
                        source_type_hint=source_type,
                        engine=f"direct_fetch:{source_id}",
                        query_id=f"df-{source_id}",
                    )
                    results.append(result)
                    if observation_sink is not None:
                        observation_sink.append(observation_from_result(
                            result,
                            source=source_id,
                            access="direct_fetch",
                            parser="direct_fetch",
                            source_url=url,
                        ))
            
            # Phase 2: fallback — "Read article" style links with backward heading lookup
            remaining = max_articles - len(results)
            if remaining > 0:
                fallback_results = _extract_read_more_links(resp.text, url, domain, locale,
                                                            category, source_id, remaining,
                                                            {r.url for r in results},
                                                            run_date, headers if resolve_article_dates else None,
                                                            timeout)
                results.extend(fallback_results)
                if observation_sink is not None:
                    for result in fallback_results:
                        observation_sink.append(observation_from_result(
                            result,
                            source=source_id,
                            access="direct_fetch",
                            parser="direct_fetch_read_more",
                            source_url=url,
                        ))
            
        except requests.RequestException as e:
            print(f"  ⚠️  direct_fetch [{source_id}]: {e}", file=sys.stderr)
            errors.append(str(e))
        except Exception as e:
            print(f"  ⚠️  direct_fetch [{source_id}] parse error: {e}", file=sys.stderr)
            errors.append(f"parse error: {e}")

    if source.get("sitemap_fallback") and len(results) < max_articles:
        seen_result_urls = {result.url for result in results}
        remaining = max_articles - len(results)
        for candidate in _fetch_sitemap_candidates(source, headers, timeout, remaining):
            link_url = candidate["url"]
            if link_url in seen_result_urls:
                continue
            published_at = candidate.get("published_at")
            if resolve_article_dates and not published_at:
                published_at = _resolve_published_at(link_url, run_date, headers, timeout)
            elif not published_at:
                published_at = _extract_date(link_url, "")
            if _is_future_date(published_at, run_date):
                published_at = None
            result = SearchResult(
                url=link_url,
                title=candidate["title"],
                snippet=candidate["title"],
                locale=locale,
                published_at=published_at,
                source_domain=extract_domain(link_url),
                source_type_hint=normalize_source_type(category),
                engine=f"direct_fetch:{source_id}-sitemap",
                query_id=f"df-{source_id}-sitemap",
            )
            results.append(result)
            seen_result_urls.add(link_url)
            if observation_sink is not None:
                observation_sink.append(observation_from_result(
                    result,
                    source=source_id,
                    access="direct_fetch",
                    parser="direct_fetch_sitemap",
                    source_url=source.get("urls", [""])[0],
                ))

    if keywords is not None:
        results, candidates = admit_results_with_candidates(
            results,
            keywords,
            source_id=source_id,
            access="direct_fetch",
        )
        if candidate_sink is not None:
            candidate_sink.extend(candidates)

    if raise_on_error and errors and not results:
        raise RuntimeError("; ".join(errors))
    
    return results


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Search configured sources from all active direct_fetch sources.
    
    Args:
        domain: Domain ID (e.g. 'storage')
        workspace: Project root path
        run_date: YYYY-MM-DD
    
    Returns:
        Combined list of SearchResult from all sources
    """
    from stratum.sourcing.watchlist.registry import get_active_sources
    
    sources = get_active_sources(domain, workspace, access="direct_fetch")
    if not sources:
        print("  ℹ️  No active direct_fetch sources", file=sys.stderr)
        return []
    
    all_results = []
    for source in sources:
        sid = source.get("id", "?")
        results = fetch_source(source, run_date)
        if results:
            print(f"  ✅ direct_fetch [{sid}]: {len(results)} articles", file=sys.stderr)
        else:
            print(f"  ⚠️  direct_fetch [{sid}]: no articles found", file=sys.stderr)
        all_results.extend(results)
    
    return all_results
