#!/usr/bin/env python3
"""enrich.py — Extract publication dates from raw search results.

Domain-agnostic. Uses regex patterns to extract dates from snippet/description text,
URL paths, and as a last resort fetches the page to extract HTML meta dates.

Input:  JSON array of raw search results ({url, title, snippet, datePublished, ...})
Output: JSON array — same records as input, datePublished filled where possible
Side effects: May make HTTP requests for date extraction (web_extract fallback)
Invariants:  input record count == output record count (no additions or deletions)
Error behavior: Records with no extractable date retain empty datePublished + date_source="none"

Usage:
    python3 enrich.py --input raw.json --output enriched.json --date 2026-05-28 [--web-extract]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

CST = timezone(timedelta(hours=8))

# ── Date patterns (ordered by reliability) ──

DATE_PATTERNS = [
    # ISO dates: 2026-05-28, 2026/05/28
    (r'\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b', "iso"),
    # CJK numeric date format.
    (r'(20\d{2})年(\d{1,2})月(\d{1,2})日', "zh"),
    # English: May 28, 2026 or 28 May 2026
    (r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})', "en_long"),
    (r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(20\d{2})', "en_short"),
    # Relative day words in English and Chinese.
    (r'(today|yesterday|今天|今日|昨天|昨日)', "relative"),
    # English relative: "X hours ago", "X days ago"
    (r'(\d+)\s*(hours?|days?)\s*ago', "relative_en"),
    # Chinese relative age expressions.
    (r'(\d+)\s*(小时前|天前|日前|分钟前)', "relative_zh"),
]

# URL path date: /2026/05/28/ or /2026-05-28-
URL_DATE_RE = re.compile(r'/(\d{4})/(\d{1,2})/(\d{1,2})/')
URL_DATE_DASH_RE = re.compile(r'/(\d{4})-(\d{1,2})-(\d{1,2})-')

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_from_match(match, pattern_type, run_date):
    """Convert a regex match to ISO date string."""
    try:
        if pattern_type == "iso":
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        elif pattern_type == "zh":
            month = match.group(2).zfill(2)
            day = match.group(3).zfill(2)
            return f"{match.group(1)}-{month}-{day}"
        elif pattern_type == "en_long":
            month_name = match.group(1)[:3].lower()
            month = str(MONTH_MAP.get(month_name, 1)).zfill(2)
            day = match.group(2).zfill(2)
            return f"{match.group(3)}-{month}-{day}"
        elif pattern_type == "en_short":
            month_name = match.group(2)[:3].lower()
            month = str(MONTH_MAP.get(month_name, 1)).zfill(2)
            day = match.group(1).zfill(2)
            return f"{match.group(3)}-{month}-{day}"
        elif pattern_type == "relative":
            word = match.group(1).lower()
            if word in ("today", "今天", "今日"):
                return run_date
            elif word in ("yesterday", "昨天", "昨日"):
                dt = datetime.fromisoformat(run_date) - timedelta(days=1)
                return dt.strftime("%Y-%m-%d")
        elif pattern_type == "relative_en":
            num = int(match.group(1))
            unit = match.group(2)
            days = num if "day" in unit else 0
            dt = datetime.fromisoformat(run_date) - timedelta(days=days)
            return dt.strftime("%Y-%m-%d")
        elif pattern_type == "relative_zh":
            num = int(match.group(1))
            unit = match.group(2)
            if "天" in unit:
                dt = datetime.fromisoformat(run_date) - timedelta(days=num)
            elif "小时" in unit or "分钟" in unit:
                dt = datetime.fromisoformat(run_date)
            else:
                dt = datetime.fromisoformat(run_date) - timedelta(days=num)
            return dt.strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        pass
    return None


def is_plausible_publication_date(
    date_str: str | None,
    run_date: str,
    *,
    max_future_days: int = 1,
    max_past_days: int = 365,
) -> bool:
    """Return True when a candidate date is plausible as a publication date."""
    if not date_str:
        return False
    try:
        dt = datetime.fromisoformat(date_str[:10])
        run_dt = datetime.fromisoformat(run_date)
    except ValueError:
        return False

    delta_days = (dt.date() - run_dt.date()).days
    if delta_days > max_future_days:
        return False
    if delta_days < -max_past_days:
        return False
    return True


def extract_date_from_url(url: str) -> str | None:
    """Extract date from URL path patterns like /2026/05/28/ or /2026-05-28-."""
    if not url:
        return None

    # Pattern: /2026/05/28/
    m = URL_DATE_RE.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"

    # Pattern: /2026-05-28-
    m = URL_DATE_DASH_RE.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"

    return None


def extract_date_from_text(text: str, run_date: str, *, max_future_days: int = 1) -> str | None:
    """Extract the first plausible date from text using regex patterns."""
    if not text:
        return None

    for pattern, ptype in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            result = parse_date_from_match(match, ptype, run_date)
            if result and not is_plausible_publication_date(
                result,
                run_date,
                max_future_days=max_future_days,
            ):
                continue
            if result:
                return result

    return None


def extract_date(text: str, run_date: str) -> str | None:
    """Backward-compatible wrapper for text date extraction."""
    return extract_date_from_text(text, run_date)


def extract_date_from_web(url: str, run_date: str | None = None) -> str | None:
    """Fetch page and extract date from HTML meta tags using curl + regex."""
    if not url:
        return None
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "8",
             "-H", "User-Agent: Mozilla/5.0 (compatible; Stratum/0.1)",
             url],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        html = result.stdout[:50000]  # first 50KB

        # Meta date tags
        for pat in [
            r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="date"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="pubdate"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="publish_date"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="DC\.date"[^>]+content="([^"]+)"',
            r'<meta[^>]+itemprop="datePublished"[^>]+content="([^"]+)"',
            r'<time[^>]+datetime="([^"]+)"',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                date_str = m.group(1)[:10]  # YYYY-MM-DD
                if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                    if run_date and not is_plausible_publication_date(date_str, run_date):
                        continue
                    return date_str

        # JSON-LD datePublished
        ld_match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        if ld_match:
            date_str = ld_match.group(1)[:10]
            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                if run_date and not is_plausible_publication_date(date_str, run_date):
                    return None
                return date_str

    except Exception:
        pass
    return None


def enrich_article(article: dict, run_date: str, *, use_web_extract: bool = False) -> dict:
    """Add datePublished if missing/empty. Respect agent-provided dates."""
    existing = str(article.get("datePublished") or article.get("published_at") or "")
    if existing and existing.strip():
        article["datePublished"] = existing
        existing_source = article.get("date_source", "")
        article["date_source"] = existing_source if existing_source and existing_source != "none" else "search_api"
        return article

    # ── Step 1: Regex from text ──
    text = f"{article.get('title', '')} {article.get('snippet', '')} {article.get('description', '')}"
    extracted = extract_date_from_text(text, run_date)
    if extracted:
        article["datePublished"] = extracted
        article["date_source"] = "snippet_regex"
        return article

    # ── Step 2: URL path extraction ──
    url_date = extract_date_from_url(article.get("url", ""))
    if url_date and is_plausible_publication_date(url_date, run_date):
        article["datePublished"] = url_date
        article["date_source"] = "url_path"
        return article

    # ── Step 3: Freshness window inference ──
    # Search engines configured with freshness=oneDay/day guarantee
    # results are from the last 24h. Infer date as run_date.
    engine = article.get("engine", "")
    if engine in ("bocha", "tavily"):
        article["datePublished"] = run_date
        article["date_source"] = "freshness_window"
        return article

    # ── Step 4: Web extract fallback ──
    if use_web_extract:
        url = article.get("url", "")
        web_date = extract_date_from_web(url, run_date)
        if web_date:
            article["datePublished"] = web_date
            article["date_source"] = "web_extract"
            return article

    article["datePublished"] = ""
    article["date_source"] = "none"
    return article


def main():
    parser = argparse.ArgumentParser(description="Extract dates from raw search results")
    parser.add_argument("--input", "-i", required=True, help="Input raw JSON array")
    parser.add_argument("--output", "-o", required=True, help="Output enriched JSON array")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYY-MM-DD)")
    parser.add_argument("--web-extract", action="store_true",
                        help="Fetch pages to extract dates from HTML meta tags (slow)")
    args = parser.parse_args()

    with open(args.input) as f:
        articles = json.load(f)

    enriched = []
    stats = {"total": len(articles), "enriched": 0, "no_date": 0,
             "sources": {}}

    for article in articles:
        result = enrich_article(article, args.date, use_web_extract=args.web_extract)
        enriched.append(result)
        source = result.get("date_source", "none")
        stats["sources"][source] = stats["sources"].get(source, 0) + 1
        if result.get("datePublished"):
            stats["enriched"] += 1
        else:
            stats["no_date"] += 1

    with open(args.output, "w") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Date enrichment complete:", file=sys.stderr)
    print(f"   Total:     {stats['total']}", file=sys.stderr)
    print(f"   Enriched:  {stats['enriched']}", file=sys.stderr)
    print(f"   No date:   {stats['no_date']}", file=sys.stderr)
    for src, count in sorted(stats["sources"].items()):
        print(f"     {src}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
