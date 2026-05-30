#!/usr/bin/env python3
"""verify.py — Deterministic article verification engine.

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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from stratum.subsystems.search.models import canonicalize_url, source_pattern_matches

CST = timezone(timedelta(hours=8))

DATE_SOURCE_CONFIDENCE = {
    "search_api": "high",
    "web_extract": "high",
    "url_path": "high",
    "freshness_window": "medium",
    "snippet_regex": "low",
    "none": "none",
    "": "none",
}
CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def load_domain_config(domain_path: str) -> dict:
    """Load pipeline section from domain.yaml."""
    with open(domain_path) as f:
        config = yaml.safe_load(f)
    return config.get("pipeline", {})


def extract_domain(url: str) -> str:
    """Extract domain from URL, stripping common presentation prefixes."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain.startswith("m."):
            domain = domain[2:]
        return domain
    except Exception:
        return ""


def is_blocklisted(url: str, blocklist: dict) -> tuple[bool, str]:
    """Check if URL domain matches any blocklist category."""
    for category, patterns in blocklist.items():
        for blocked in patterns:
            if source_pattern_matches(url, blocked):
                return True, f"BLOCKED: {blocked}"
    return False, ""


def is_low_priority_domain(url: str, low_priority_domains: set[str]) -> bool:
    """Check whether URL belongs to a low-priority exact domain or subdomain."""
    return any(source_pattern_matches(url, pattern) for pattern in low_priority_domains)


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


def date_confidence_for_source(date_source: str) -> str:
    """Map date lineage to a deterministic confidence bucket."""
    return DATE_SOURCE_CONFIDENCE.get(date_source or "", "low")


def date_confidence_meets_minimum(confidence: str, minimum: str) -> bool:
    """Return whether a confidence bucket satisfies a configured minimum."""
    return CONFIDENCE_RANK.get(confidence, 0) >= CONFIDENCE_RANK.get(minimum, 0)


def validate_date(article: dict, run_date_str: str, date_window: dict) -> tuple[bool, str, str | None, str]:
    """Validate article date against run_date window."""
    stale_days = date_window.get("stale_days", 2)
    max_future_days = date_window.get("max_future_days", 1)

    date_str = extract_date_from_metadata(article)
    date_source = article.get("date_source", "")

    if not date_str:
        snippet = article.get("snippet", "") or article.get("description", "")
        title = article.get("title", "")
        text = f"{title} {snippet}"
        date_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', text)
        if date_match:
            date_str = date_match.group(1)
            date_source = date_source or "snippet_regex"
        else:
            return False, "NO_DATE", None, date_source or "none"
    elif not date_source:
        date_source = "search_api"

    dt = parse_date(date_str)
    if dt is None:
        return False, "NO_DATE", None, date_source

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)

    run_date = datetime.fromisoformat(run_date_str).replace(tzinfo=CST)
    diff_days = (run_date - dt).days

    if diff_days < -max_future_days:
        return False, "FUTURE", dt.isoformat(), date_source
    if diff_days > stale_days:
        return False, "STALE", dt.isoformat(), date_source

    return True, "verified", dt.isoformat(), date_source


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
    """Deduplication: canonical URL match or title similarity > 0.85."""
    canonical_url = canonicalize_url(url)
    if canonical_url and canonical_url in seen_urls:
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


def build_verification_stats(verified_records: list[dict], run_date: str) -> dict:
    """Build a deterministic sidecar summary for verification output."""
    stats = {
        "date": run_date,
        "total": len(verified_records),
        "verified": 0,
        "rejected": 0,
        "reasons": {},
        "date_confidence": {},
        "quality_flags": {},
        "blocklisted": 0,
        "duplicates": 0,
        "platform_admitted": 0,
    }
    for record in verified_records:
        status = record.get("verification_status")
        if status == "verified":
            stats["verified"] += 1
            date_confidence = record.get("date_confidence", "none")
            stats["date_confidence"][date_confidence] = stats["date_confidence"].get(date_confidence, 0) + 1
            for flag in record.get("quality_flags", []) or []:
                stats["quality_flags"][flag] = stats["quality_flags"].get(flag, 0) + 1
            if record.get("platform_admitted"):
                stats["platform_admitted"] += 1
        else:
            stats["rejected"] += 1
            reason = record.get("rejection_reason", "unknown")
            stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
            if "BLOCKED" in str(reason):
                stats["blocklisted"] += 1
            if "DUPLICATE" in str(reason):
                stats["duplicates"] += 1
    return stats


def default_stats_path(output_path: str | None) -> str | None:
    """Resolve the default verification stats sidecar path."""
    if not output_path:
        return None
    base, _ext = os.path.splitext(output_path)
    return f"{base}.stats.json"


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
    canonical_url = article.get("canonical_url") or canonicalize_url(url)
    title = article.get("title", "")

    verified = {
        "id": article.get("id", f"raw-{index:04d}"),
        "url": url,
        "canonical_url": canonical_url,
        "title": title,
        "source": extract_domain(url),
        "snippet": article.get("snippet", "") or article.get("description", ""),
        "query_used": article.get("query_used", ""),
        "engine": article.get("engine", "unknown"),
        "date_source": article.get("date_source", ""),
        "raw_metadata": {k: v for k, v in article.items()
                        if k not in ("id", "url", "canonical_url", "title", "snippet", "description")},
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
    if is_low_priority_domain(url, low_priority):
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = "LOW_SIGNAL"
        verified["published_at"] = None
        return verified

    # Check 3: Date validation
    passed, status, parsed_date, date_source = validate_date(article, run_date, date_window)
    verified["published_at"] = parsed_date
    verified["date_source"] = date_source
    date_confidence = date_confidence_for_source(date_source)
    verified["date_confidence"] = date_confidence

    if not passed:
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = status
        return verified

    if date_confidence == "low":
        verified["quality_flags"] = ["LOW_CONFIDENCE_DATE"]

    min_date_confidence = date_window.get("min_date_confidence", "low")
    if not date_confidence_meets_minimum(date_confidence, min_date_confidence):
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = "LOW_CONFIDENCE_DATE"
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
    if canonical_url:
        seen_urls.add(canonical_url)
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
    parser.add_argument("--stats", help="Output JSON stats sidecar; defaults next to --output")
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
    seen_urls = set()
    seen_titles = {}

    for i, article in enumerate(raw_articles):
        result = verify_article(
            article, args.date, i, pipeline_config,
            seen_urls=seen_urls, seen_titles=seen_titles,
            platform_companies=platform_companies,
        )
        verified.append(result)

    stats = build_verification_stats(verified, args.date)

    output_lines = [json.dumps(v, ensure_ascii=False) for v in verified]
    output_text = "\n".join(output_lines) + "\n"

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_text)
    else:
        sys.stdout.write(output_text)

    stats_path = args.stats or default_stats_path(args.output)
    if stats_path:
        os.makedirs(os.path.dirname(stats_path) or ".", exist_ok=True)
        with open(stats_path, "w") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Verification complete:", file=sys.stderr)
    print(f"   Total:    {stats['total']}", file=sys.stderr)
    print(f"   Verified: {stats['verified']}", file=sys.stderr)
    print(f"   Rejected: {stats['rejected']}", file=sys.stderr)
    if stats["date_confidence"]:
        print(f"   Date confidence: {stats['date_confidence']}", file=sys.stderr)
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
