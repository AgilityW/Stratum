#!/usr/bin/env python3
"""verify.py — Deterministic article verification engine.

from __future__ import annotations

Domain-agnostic. All rules (blocklist, date window, magnitude checks) loaded from domain.yaml.

Input:  JSON array of enriched search results (with datePublished from enrich stage)
Output: JSONL — one record per input, each with {verification_status, rejection_reason, published_at, ...}
Side effects: None. Pure function — reads input file + domain.yaml, writes output file.
Invariants:  input count == output count; every record has verification_status ∈ {verified, rejected}
Error behavior: Records failing blocklist → rejected. No date → NO_DATE. Future date → FUTURE. Stale date → STALE.

Usage:
    python3 verify.py --input enriched.json --output verified.jsonl \
        --date 2026-05-28 --domain domains/storage/domain.yaml
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import yaml
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

CST = timezone(timedelta(hours=8))


def load_domain_config(domain_path: str) -> dict:
    """Load pipeline section from domain.yaml."""
    with open(domain_path) as f:
        config = yaml.safe_load(f)
    return config.get("pipeline", {})


def extract_domain(url: str) -> str:
    """Extract domain from URL, stripping www prefix."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def is_blocklisted(url: str, blocklist: dict) -> tuple[bool, str]:
    """Check if URL domain matches any blocklist category."""
    domain = extract_domain(url)
    for category, patterns in blocklist.items():
        for blocked in patterns:
            if blocked in domain:
                return True, f"BLOCKED: {blocked}"
    return False, ""


def extract_date_from_metadata(article: dict) -> str | None:
    """Extract publication date from search API metadata."""
    if "datePublished" in article:
        return article["datePublished"]
    if "date_published" in article:
        return article["date_published"]
    if "published_date" in article:
        return article["published_date"]
    for key in ["publishedAt", "pubDate", "date", "timestamp"]:
        if key in article:
            return article[key]
    return None


def parse_date(date_str: str) -> datetime | None:
    """Parse various date formats to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%B %d, %Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    return None


def validate_date(article: dict, run_date_str: str, date_window: dict) -> tuple[bool, str, str | None]:
    """Validate article date against run_date window."""
    stale_days = date_window.get("stale_days", 2)
    max_future_days = date_window.get("max_future_days", 1)

    date_str = extract_date_from_metadata(article)

    if not date_str:
        snippet = article.get("snippet", "") or article.get("description", "")
        title = article.get("title", "")
        text = f"{title} {snippet}"
        date_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', text)
        if date_match:
            date_str = date_match.group(1)
        else:
            return False, "NO_DATE", None

    dt = parse_date(date_str)
    if dt is None:
        return False, "NO_DATE", None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)

    run_date = datetime.fromisoformat(run_date_str).replace(tzinfo=CST)
    diff_days = (run_date - dt).days

    if diff_days < -max_future_days:
        return False, "FUTURE", dt.isoformat()
    if diff_days > stale_days:
        return False, "STALE", dt.isoformat()

    return True, "verified", dt.isoformat()


def check_magnitude(article: dict, magnitude_rules: dict) -> list[str]:
    """Check for implausible magnitude claims in snippet/title."""
    flags = []
    text = f"{article.get('title', '')} {article.get('snippet', '')}"

    share_max = magnitude_rules.get("share_max_pct", 100)
    share_match = re.search(r'(\d+(?:\.\d+)?)\s*%\s*(?:market\s*)?share', text, re.IGNORECASE)
    if share_match:
        share = float(share_match.group(1))
        if share > share_max:
            flags.append(f"IMPOSSIBLE: market share {share}% > {share_max}%")

    rev_max = magnitude_rules.get("revenue_max_usd", 1_000_000_000_000)
    rev_match = re.search(r'\$?\s*(\d+(?:\.\d+)?)\s*(?:trillion|T)\b', text, re.IGNORECASE)
    if rev_match:
        rev = float(rev_match.group(1))
        if rev >= 1.0:
            flags.append(f"FLAG: revenue ${rev}T exceeds sanity threshold")

    return flags


def check_duplicate(url: str, title: str, seen_urls: set, seen_titles: dict) -> tuple[bool, str]:
    """Deduplication: URL exact match or title similarity > 0.85."""
    # URL exact match
    if url and url in seen_urls:
        return True, "DUPLICATE_URL"
    # Title similarity
    if title:
        title_lower = title.lower().strip()
        for seen_title, seen_url in seen_titles.items():
            if _title_similarity(title_lower, seen_title) > 0.85:
                return True, f"DUPLICATE_TITLE: similar to '{seen_title[:60]}'"
    return False, ""

def _title_similarity(a: str, b: str) -> float:
    """Jaccard-like similarity on character bigrams for CJK-friendly comparison."""
    def _bigrams(s: str) -> set:
        return {s[i:i+2] for i in range(len(s)-1)}
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)

def check_platform_admission(domain: str, platform_companies: list[str]) -> tuple[bool, str]:
    """Check if non-domain source is in platform admission list.
    Returns (is_platform, reason). is_platform=True means it's admitted
    (a platform company that affects our industry)."""
    if not platform_companies or not domain:
        return False, ""
    domain_lower = domain.lower()
    for name in platform_companies:
        if name.lower() in domain_lower:
            return True, f"PLATFORM_ADMIT: {name}"
    # Not a platform company — no special treatment
    return False, ""


def verify_article(article: dict, run_date: str, index: int,
                   pipeline_config: dict,
                   seen_urls: set = None,
                   seen_titles: dict = None,
                   platform_companies: list[str] = None) -> dict:
    """Verify a single article. Returns article with verification fields set."""
    blocklist = pipeline_config.get("blocklist", {})
    low_priority = set(pipeline_config.get("low_priority_domains", []))
    magnitude_rules = pipeline_config.get("magnitude_rules", {})
    date_window = pipeline_config.get("date_window", {})
    seen_urls = set() if seen_urls is None else seen_urls
    seen_titles = {} if seen_titles is None else seen_titles
    platform_companies = platform_companies or []

    url = article.get("url", "")
    title = article.get("title", "")

    verified = {
        "id": article.get("id", f"raw-{index:04d}"),
        "url": url,
        "title": title,
        "source": extract_domain(url),
        "snippet": article.get("snippet", "") or article.get("description", ""),
        "query_used": article.get("query_used", ""),
        "engine": article.get("engine", "unknown"),
        "raw_metadata": {k: v for k, v in article.items()
                        if k not in ("id", "url", "title", "snippet", "description")},
    }

    # Check 1: Blocklist
    is_blocked, block_reason = is_blocklisted(url, blocklist)
    if is_blocked:
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = block_reason
        verified["published_at"] = None
        return verified

    # Check 2: Low priority domains
    domain = extract_domain(url)
    if domain in low_priority:
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = "LOW_SIGNAL"
        verified["published_at"] = None
        return verified

    # Check 3: Date validation
    passed, status, parsed_date = validate_date(article, run_date, date_window)
    verified["published_at"] = parsed_date

    if not passed:
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = status
        return verified

    # Check 4: Magnitude sanity
    magnitude_flags = check_magnitude(article, magnitude_rules)
    if any("IMPOSSIBLE" in f for f in magnitude_flags):
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = magnitude_flags[0]
        verified["magnitude_flags"] = magnitude_flags
        return verified

    # Check 5: Deduplication
    is_dup, dup_reason = check_duplicate(url, title, seen_urls, seen_titles)
    if is_dup:
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = dup_reason
        return verified

    # Check 6: Platform admission (not a rejection — marks special source)
    is_platform, platform_reason = check_platform_admission(domain, platform_companies)
    if is_platform:
        verified["platform_admitted"] = True
        verified["platform_reason"] = platform_reason

    # Track for dedup
    if url:
        seen_urls.add(url)
    if title:
        seen_titles[title.lower().strip()] = url

    verified["verification_status"] = "verified"
    verified["rejection_reason"] = None
    if magnitude_flags:
        verified["magnitude_flags"] = magnitude_flags

    return verified


def main():
    parser = argparse.ArgumentParser(description="Deterministic article verification")
    parser.add_argument("--input", "-i", help="Input JSON file (enriched results array)")
    parser.add_argument("--output", "-o", help="Output JSONL file")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYY-MM-DD)")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)

    # Load platform admission from domain.yaml editorial section
    domain_cfg_full = {}
    with open(args.domain) as f:
        domain_cfg_full = yaml.safe_load(f)
    platform_companies = (
        domain_cfg_full.get("editorial", {})
        .get("platform_admission", {})
        .get("companies", [])
    )

    # Load input
    if args.input:
        with open(args.input) as f:
            raw_articles = json.load(f)
    else:
        raw_articles = json.load(sys.stdin)

    if not isinstance(raw_articles, list):
        print("Error: input must be a JSON array", file=sys.stderr)
        sys.exit(1)

    verified = []
    stats = {"total": len(raw_articles), "verified": 0, "rejected": 0,
             "reasons": {}, "blocklisted": 0, "duplicates": 0, "platform_admitted": 0}
    seen_urls = set()
    seen_titles = {}

    for i, article in enumerate(raw_articles):
        result = verify_article(
            article, args.date, i, pipeline_config,
            seen_urls=seen_urls, seen_titles=seen_titles,
            platform_companies=platform_companies,
        )
        verified.append(result)

        status = result["verification_status"]
        if status == "verified":
            stats["verified"] += 1
            if result.get("platform_admitted"):
                stats["platform_admitted"] += 1
        else:
            stats["rejected"] += 1
            reason = result.get("rejection_reason", "unknown")
            stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
            if "BLOCKED" in str(reason):
                stats["blocklisted"] += 1
            if "DUPLICATE" in str(reason):
                stats["duplicates"] += 1

    output_lines = [json.dumps(v, ensure_ascii=False) for v in verified]
    output_text = "\n".join(output_lines) + "\n"

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_text)
    else:
        sys.stdout.write(output_text)

    print(f"\n📊 Verification complete:", file=sys.stderr)
    print(f"   Total:    {stats['total']}", file=sys.stderr)
    print(f"   Verified: {stats['verified']}", file=sys.stderr)
    print(f"   Rejected: {stats['rejected']}", file=sys.stderr)
    print(f"   Blocked:  {stats['blocklisted']}", file=sys.stderr)
    if stats["duplicates"]:
        print(f"   Duplicates: {stats['duplicates']}", file=sys.stderr)
    if stats["platform_admitted"]:
        print(f"   Platform admitted: {stats['platform_admitted']}", file=sys.stderr)
    for reason, count in sorted(stats["reasons"].items(), key=lambda x: -x[1]):
        print(f"     {reason}: {count}", file=sys.stderr)

    if stats["verified"] == 0 and stats["total"] > 0:
        print("⚠️  WARNING: All articles rejected!", file=sys.stderr)


if __name__ == "__main__":
    main()
