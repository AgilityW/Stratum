"""RSS watchlist — fetch and parse RSS/Atom feeds.

Reads active sources with access=rss from domain.yaml's source_registry. For
each feed URL, fetches the XML, parses articles (RSS 2.0 or Atom), applies
watchlist admission scoring, and returns normalized SearchResult objects.

Uses stdlib xml.etree.ElementTree — zero external dependencies.
"""

import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Optional
from xml.etree import ElementTree as ET

import requests

from stratum.sourcing.watchlist.common import extract_domain, normalize_source_type
from stratum.sourcing.discovery import SearchResult


# ── Date parsing ──

def _parse_rss_date(date_str: str) -> Optional[str]:
    """Parse RSS pubDate (RFC 2822) or Atom published (ISO 8601). Returns YYYY-MM-DD."""
    if not date_str:
        return None
    date_str = date_str.strip()
    
    # Try ISO 8601: 2026-05-30T12:00:00Z or 2026-05-30T12:00:00+09:00
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
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

def _parse_rss_feed(xml_text: str, raise_on_error: bool = False) -> list[dict]:
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
        if raise_on_error:
            raise
        pass
    
    return articles


def _parse_atom_feed(xml_text: str, raise_on_error: bool = False) -> list[dict]:
    """Parse Atom feed. Returns list of {title, url, snippet, published_at}."""
    articles = []
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    try:
        root = ET.fromstring(xml_text)
        
        for entry in root.findall('atom:entry', ns) or root.findall('entry'):
            title = _text(entry, 'title', ns)
            
            # Atom <link> has href attribute
            url = ''
            link = entry.find('atom:link', ns)
            if link is None:
                link = entry.find('link')
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
        if raise_on_error:
            raise
        pass
    
    return articles


def _parse_any_feed(xml_text: str, raise_on_error: bool = False) -> list[dict]:
    """Auto-detect feed type and parse."""
    articles = _parse_rss_feed(xml_text, raise_on_error=raise_on_error)
    if not articles:
        articles = _parse_atom_feed(xml_text, raise_on_error=raise_on_error)
    return articles


# ── Helpers ──

def _text(element, tag: str, ns: Optional[dict] = None) -> str:
    """Get element text safely."""
    child = None
    if ns and ":" not in tag and "atom" in ns:
        child = element.find(f"atom:{tag}", ns)
    if child is None:
        child = element.find(tag, ns) if ns else element.find(tag)
    return child.text.strip() if child is not None and child.text else ''


_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(text: str) -> str:
    """Remove HTML tags from text for clean snippets."""
    return unescape(_HTML_TAG_RE.sub('', text)).strip()


# ── Keyword extraction from domain.yaml ──
# Delegated to stratum.sourcing.watchlist.keywords (shared by watchlist acquisition)


# ── Main collection ──

def fetch_feed(
    url: str,
    keywords: list[str],
    source_id: str,
    locale: str,
    category: str,
    timeout: int = 15,
    raise_on_error: bool = False,
    observation_sink: list[dict] | None = None,
    candidate_sink: list[dict] | None = None,
) -> list[SearchResult]:
    """Fetch and parse a single RSS feed through watchlist admission scoring."""
    from stratum.sourcing.watchlist.keywords import admission_decision
    from stratum.sourcing.watchlist.observations import observation_record
    results = []
    source_type = normalize_source_type(category)
    
    headers = {
        "User-Agent": "Stratum/1.0 (storage industry monitor; +https://github.com/stratum)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        
        articles = _parse_any_feed(resp.text, raise_on_error=raise_on_error)
        
        accepted_by_status = {"accept": 0, "weak_signal": 0}
        rejected = 0
        for art in articles:
            if observation_sink is not None:
                observation_sink.append(observation_record(
                    source=source_id,
                    access="rss",
                    url=art["url"],
                    title=art["title"],
                    snippet=art["snippet"],
                    published_at=art.get("published_at"),
                    locale=locale,
                    source_domain=extract_domain(art["url"]),
                    source_type_hint=source_type,
                    engine=f"rss:{source_id}",
                    query_id=f"rss-{source_id}",
                    parser="rss",
                    source_url=url,
                ))
            decision = admission_decision(
                art['title'],
                art['snippet'],
                keywords,
                source_type=source_type,
                published_at=art.get('published_at'),
            )
            if candidate_sink is not None:
                candidate_sink.append({
                    "source": source_id,
                    "access": "rss",
                    "url": art["url"],
                    "title": art["title"],
                    "snippet": art["snippet"],
                    "locale": locale,
                    "published_at": art.get("published_at"),
                    "source_domain": extract_domain(art["url"]),
                    "source_type_hint": source_type,
                    "engine": f"rss:{source_id}",
                    "query_id": f"rss-{source_id}",
                    "status": decision.status,
                    "accepted": decision.accepted,
                    "score": decision.score,
                    "matched_keywords": list(decision.matched_keywords),
                    "reason": decision.reason,
                })
            if not decision.accepted:
                rejected += 1
                continue

            result = SearchResult(
                url=art['url'],
                title=art['title'],
                snippet=art['snippet'],
                locale=locale,
                published_at=art.get('published_at'),
                source_domain=extract_domain(art['url']),
                source_type_hint=source_type,
                engine=f"rss:{source_id}",
                query_id=f"rss-{source_id}",
                score=decision.score,
                query_dimension=decision.status,
            )
            results.append(result)
            accepted_by_status[decision.status] = accepted_by_status.get(decision.status, 0) + 1
        
        if results:
            total = len(articles)
            kept = len(results)
            weak = accepted_by_status.get("weak_signal", 0)
            print(
                f"  ✅ rss [{source_id}]: {kept}/{total} admitted "
                f"({weak} weak signals, {rejected} rejected)",
                file=sys.stderr,
            )
        else:
            print(f"  ⚠️  rss [{source_id}]: {len(articles)} articles, 0 admitted", file=sys.stderr)
            
    except requests.RequestException as e:
        print(f"  ⚠️  rss [{source_id}]: {e}", file=sys.stderr)
        if raise_on_error:
            raise
    except ET.ParseError as e:
        print(f"  ⚠️  rss [{source_id}]: XML parse error: {e}", file=sys.stderr)
        if raise_on_error:
            raise
    
    return results


def collect(domain: str, workspace: str, run_date: str) -> list[SearchResult]:
    """Collect configured sources from all active RSS sources."""
    from stratum.sourcing.watchlist.keywords import load_keywords
    from stratum.sourcing.watchlist.registry import get_active_sources
    
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
