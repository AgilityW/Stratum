"""Direct fetch collector — HTTP GET newsroom pages, parse article links.

Reads active sources with access=direct_fetch from domain.yaml's source_registry.
For each source URL, fetches the page, extracts article links and metadata,
and returns normalized SearchResult objects.

HTML parsing uses stdlib html.parser + regex for date extraction.
No external dependencies required.
"""

import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

from stratum.subsystems.search.models import SearchResult


# ── Date extraction patterns ──
# ISO dates in URLs and text: 2026-05-30, 2026/05/30
_DATE_IN_URL = re.compile(r'/(\d{4})[/-](\d{2})[/-](\d{2})[/-]')
# Text dates: "May 30, 2026", "30 May 2026", "2026年5月30日"
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
            title = ' '.join(t for t in self._link_text if t).strip()
            
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
                              seen_urls: set) -> list[SearchResult]:
    """Extract articles from 'Read article' style links by looking backward for headings.
    
    Used as fallback when heading-first extraction doesn't capture all articles
    (common on AEM and corporate CMS sites where article titles are in separate
    elements from the read-more button).
    """
    results = []
    
    # Match: <a href="...">Read article</a> or <a href="...">Learn More</a>
    pattern = re.compile(
        r'<a[^>]*href="([^"]*)"[^>]*>\s*(Read article|Learn [Mm]ore|READ)\s*</a>',
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
        
        # Clean heading text (remove HTML tags)
        title = re.sub(r'<[^>]+>', '', headings[-1]).strip()
        
        if len(title) < 10:
            continue
        
        # Extract date
        published_at = _extract_date(full_url, html)
        
        result = SearchResult(
            url=full_url,
            title=title,
            snippet=title,
            locale=locale,
            published_at=published_at,
            source_domain=domain,
            source_type_hint=category,
            engine=f"direct_fetch:{source_id}",
            query_id=f"df-{source_id}-fallback",
        )
        results.append(result)
        seen_urls.add(full_url)
    
    return results


def fetch_source(source: dict, run_date: str, timeout: int = 15) -> list[SearchResult]:
    """Fetch articles from a single source definition.
    
    Args:
        source: Source dict from domain.yaml source_registry
        run_date: YYYY-MM-DD for freshness filtering
        timeout: HTTP timeout in seconds
    
    Returns:
        List of SearchResult (may be empty on failure)
    """
    results = []
    source_id = source.get("id", "unknown")
    source_name = source.get("name", source_id)
    locale = source.get("locale", "en")
    category = source.get("category", "media")
    urls = source.get("urls", [])
    max_articles = source.get("max_articles", source.get("defaults", {}).get("max_articles_per_url", 10))
    timeout = source.get("timeout", 15)
    
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
            
            domain = urlparse(url).netloc.lower().lstrip("www.")
            
            # Detect page structure: AEM/corp CMS with "Read article" buttons
            has_read_more = bool(re.search(
                r'<a[^>]*>\s*(Read article|Learn [Mm]ore|READ)\s*</a>',
                resp.text, re.IGNORECASE
            ))
            
            # Phase 1: heading-first links (skip if page has read-more buttons)
            if not has_read_more:
                added = 0
                for link in parser.links:
                    if added >= max_articles:
                        break
                        
                    link_url = link['url']
                    title = link['title']
                    
                    if len(title) < 10 or title.lower() in ('read article', 'learn more', 'read more', 'click here', 'read', 'press releases', 'newsroom'):
                        continue
                    
                    if len(title.split()) <= 2 and title == title.upper():
                        continue
                    
                    published_at = _extract_date(link_url, resp.text)
                    
                    result = SearchResult(
                        url=link_url,
                        title=title,
                        snippet=title,
                        locale=locale,
                        published_at=published_at,
                        source_domain=domain,
                        source_type_hint=category,
                        engine=f"direct_fetch:{source_id}",
                        query_id=f"df-{source_id}",
                    )
                    results.append(result)
                    added += 1
            
            # Phase 2: fallback — "Read article" style links with backward heading lookup
            remaining = max_articles - len(results)
            if remaining > 0:
                results.extend(_extract_read_more_links(resp.text, url, domain, locale, 
                                                         category, source_id, remaining,
                                                         {r.url for r in results}))
            
        except requests.RequestException as e:
            print(f"  ⚠️  direct_fetch [{source_id}]: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  direct_fetch [{source_id}] parse error: {e}", file=sys.stderr)
    
    return results


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Collect articles from all active direct_fetch sources.
    
    Args:
        domain: Domain ID (e.g. 'storage')
        workspace: Project root path
        run_date: YYYY-MM-DD
    
    Returns:
        Combined list of SearchResult from all sources
    """
    from stratum.collectors.registry import get_active_sources
    
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
