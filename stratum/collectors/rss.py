"""RSS collector — fetch and parse RSS/Atom feeds.

Reads active sources with access=rss from domain.yaml's source_registry.
For each feed URL, fetches the XML, parses articles (RSS 2.0 or Atom),
filters by domain-specific keywords from domain.yaml, and returns
normalized SearchResult objects.

Uses stdlib xml.etree.ElementTree — zero external dependencies.
"""

import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests

from stratum.subsystems.search.models import SearchResult


# ── Date parsing ──

def _parse_rss_date(date_str: str) -> Optional[str]:
    """Parse RSS pubDate (RFC 2822) or Atom published (ISO 8601). Returns YYYY-MM-DD."""
    if not date_str:
        return None
    date_str = date_str.strip()
    
    # Try ISO 8601: 2026-05-30T12:00:00Z or 2026-05-30T12:00:00+09:00
    try:
        # Handle timezone offset
        clean = re.sub(r'(\d{2}:\d{2})$', r'\1:00', date_str)
        dt = datetime.fromisoformat(clean.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        pass
    
    # Try RFC 2822: "Thu, 28 May 2026 15:02:21 GMT"
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        pass
    
    return None


# ── Feed parsing ──

def _parse_rss_feed(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 feed. Returns list of {title, url, snippet, published_at}."""
    articles = []
    try:
        root = ET.fromstring(xml_text)
        channel = root.find('channel')
        if channel is None:
            return articles
        
        for item in channel.findall('item'):
            title = _text(item, 'title')
            url = _text(item, 'link')
            snippet = _text(item, 'description') or ''
            pubdate = _text(item, 'pubDate')
            
            if title and url:
                articles.append({
                    'title': title.strip(),
                    'url': url.strip(),
                    'snippet': _strip_html(snippet)[:300],
                    'published_at': _parse_rss_date(pubdate),
                })
    except ET.ParseError:
        pass
    
    return articles


def _parse_atom_feed(xml_text: str) -> list[dict]:
    """Parse Atom feed. Returns list of {title, url, snippet, published_at}."""
    articles = []
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    try:
        root = ET.fromstring(xml_text)
        
        for entry in root.findall('atom:entry', ns) or root.findall('entry'):
            title = _text(entry, 'title', ns)
            
            # Atom <link> has href attribute
            url = ''
            link = entry.find('atom:link', ns) or entry.find('link')
            if link is not None:
                url = link.get('href', '')
            
            snippet = (_text(entry, 'summary', ns) or 
                      _text(entry, 'content', ns) or '')
            published = (_text(entry, 'published', ns) or 
                        _text(entry, 'updated', ns))
            
            if title and url:
                articles.append({
                    'title': title.strip(),
                    'url': url.strip(),
                    'snippet': _strip_html(snippet)[:300],
                    'published_at': _parse_rss_date(published),
                })
    except ET.ParseError:
        pass
    
    return articles


def _parse_any_feed(xml_text: str) -> list[dict]:
    """Auto-detect feed type and parse."""
    articles = _parse_rss_feed(xml_text)
    if not articles:
        articles = _parse_atom_feed(xml_text)
    return articles


# ── Helpers ──

def _text(element, tag: str, ns: Optional[dict] = None) -> str:
    """Get element text safely."""
    child = element.find(tag, ns) if ns else element.find(tag)
    return child.text.strip() if child is not None and child.text else ''


_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(text: str) -> str:
    """Remove HTML tags from text for clean snippets."""
    return _HTML_TAG_RE.sub('', text).strip()


# ── Keyword extraction from domain.yaml ──
# Delegated to stratum.collectors.keywords (shared by all collectors)


# ── Main collection ──

def fetch_feed(url: str, keywords: list[str], source_id: str,
               locale: str, category: str, timeout: int = 15) -> list[SearchResult]:
    """Fetch and parse a single RSS feed. Keywords filtered via keywords.match_keywords."""
    from stratum.collectors.keywords import match_keywords
    results = []
    domain = urlparse(url).netloc.lower().lstrip("www.")
    
    headers = {
        "User-Agent": "Stratum/1.0 (storage industry monitor; +https://github.com/stratum)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        
        articles = _parse_any_feed(resp.text)
        
        for art in articles:
            # Filter by domain keywords
            if not match_keywords(art['title'], art['snippet'], keywords):
                continue
            
            result = SearchResult(
                url=art['url'],
                title=art['title'],
                snippet=art['snippet'],
                locale=locale,
                published_at=art.get('published_at'),
                source_domain=domain,
                source_type_hint=category,
                engine=f"rss:{source_id}",
                query_id=f"rss-{source_id}",
            )
            results.append(result)
        
        if results:
            total = len(articles)
            kept = len(results)
            print(f"  ✅ rss [{source_id}]: {kept}/{total} matched keywords", file=sys.stderr)
        else:
            print(f"  ⚠️  rss [{source_id}]: {len(articles)} articles, 0 matched keywords", file=sys.stderr)
            
    except requests.RequestException as e:
        print(f"  ⚠️  rss [{source_id}]: {e}", file=sys.stderr)
    except ET.ParseError as e:
        print(f"  ⚠️  rss [{source_id}]: XML parse error: {e}", file=sys.stderr)
    
    return results


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Collect articles from all active RSS sources."""
    from stratum.collectors.keywords import load_keywords
    from stratum.collectors.registry import get_active_sources
    
    sources = get_active_sources(domain, workspace, access="rss")
    if not sources:
        return []
    
    keywords = load_keywords(domain, workspace)
    
    all_results = []
    for source in sources:
        sid = source.get("id", "?")
        locale = source.get("locale", "en")
        category = source.get("category", "media")
        urls = source.get("urls", [])
        timeout = source.get("timeout", 15)
        
        for url in urls:
            results = fetch_feed(url, keywords, sid, locale, category, timeout)
            all_results.extend(results)
    
    return all_results
