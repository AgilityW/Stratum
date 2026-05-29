#!/usr/bin/env python3
"""enrich.py — Extract publication dates from raw search results.

Domain-agnostic. Uses regex patterns to extract dates from snippet/description text.
No domain-specific data.

Input: raw search results JSON array (url, title, snippet, datePublished, ...)
Output: same array with datePublished filled where possible

Usage:
    python3 enrich.py --input raw.json --output enriched.json --date 2026-05-28
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# Date patterns in snippets (ordered by reliability)
DATE_PATTERNS = [
    # ISO dates: 2026-05-28, 2026/05/28
    (r'\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b', "iso"),
    # Chinese: 2026年5月28日
    (r'(20\d{2})年(\d{1,2})月(\d{1,2})日', "zh"),
    # Japanese: 2026年5月28日
    (r'(20\d{2})年(\d{1,2})月(\d{1,2})日', "ja"),
    # English: May 28, 2026 or 28 May 2026
    (r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})', "en_long"),
    (r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(20\d{2})', "en_short"),
    # Relative: "today", "yesterday", "2 days ago"
    (r'(today|yesterday|今天|昨天|昨日)', "relative"),
    # "X hours ago", "X days ago"
    (r'(\d+)\s*(hours?|days?)\s*ago', "relative_en"),
    (r'(\d+)\s*(小时|天|日前)', "relative_zh"),
]

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_from_match(match, pattern_type, run_date):
    """Convert a regex match to ISO date string."""
    try:
        if pattern_type == "iso":
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        elif pattern_type in ("zh", "ja"):
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
            if word in ("today", "今天"):
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
            elif "小时" in unit:
                dt = datetime.fromisoformat(run_date)
            else:
                dt = datetime.fromisoformat(run_date) - timedelta(days=num)
            return dt.strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        pass
    return None


def extract_date(text, run_date):
    """Extract the FIRST plausible date from text."""
    if not text:
        return None

    for pattern, ptype in DATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = parse_date_from_match(match, ptype, run_date)
            if result:
                try:
                    dt = datetime.fromisoformat(result)
                    run_dt = datetime.fromisoformat(run_date)
                    diff = abs((run_dt - dt).days)
                    if diff > 365:
                        continue
                except ValueError:
                    continue
                return result

    return None


def enrich_article(article, run_date):
    """Add datePublished if missing/empty. Respect agent-provided dates."""
    existing = article.get("datePublished", "")
    if existing and existing.strip():
        article["date_source"] = "web_extract"
        return article

    text = f"{article.get('title', '')} {article.get('snippet', '')} {article.get('description', '')}"
    extracted = extract_date(text, run_date)

    article["datePublished"] = extracted or ""
    article["date_source"] = "snippet_regex" if extracted else "none"
    return article


def main():
    parser = argparse.ArgumentParser(description="Extract dates from raw search results")
    parser.add_argument("--input", "-i", required=True, help="Input raw JSON array")
    parser.add_argument("--output", "-o", required=True, help="Output enriched JSON array")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYY-MM-DD)")
    args = parser.parse_args()

    with open(args.input) as f:
        articles = json.load(f)

    enriched = []
    stats = {"total": len(articles), "enriched": 0, "no_date": 0}

    for article in articles:
        result = enrich_article(article, args.date)
        enriched.append(result)
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


if __name__ == "__main__":
    main()
