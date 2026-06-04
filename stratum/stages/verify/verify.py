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
import sys
import yaml
from datetime import datetime, timezone, timedelta

from stratum.sourcing.discovery import canonicalize_url
from stratum.stages.verify.evidence_acceptance import (
    EvidenceAcceptancePolicy,
    check_duplicate,
    check_magnitude,
    check_platform_admission,
    extract_domain,
    is_blocklisted,
    is_low_priority_domain,
)
from stratum.stages.verify.freshness_policy import (
    FreshnessPolicy,
    background_flags_for_date_failure,
    date_confidence_for_source,
    date_confidence_meets_minimum,
    validate_date,
)

CST = timezone(timedelta(hours=8))

def load_domain_config(domain_path: str) -> dict:
    """Load pipeline section from domain.yaml."""
    with open(domain_path) as f:
        config = yaml.safe_load(f)
    return config.get("pipeline", {})

def extract_date_from_metadata(article: dict) -> str | None:
    """Extract publication date from search API metadata."""
    if "datePublished" in article:
        return article["datePublished"]
    if "date_published" in article:
        return article["date_published"]
    if "published_date" in article:
        return article["published_date"]
    for key in ["published_at", "publishedAt", "pubDate", "date", "timestamp"]:
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

def _source_type_hint(article: dict) -> str:
    raw = article.get("raw_metadata", {}) if isinstance(article.get("raw_metadata"), dict) else {}
    return str(
        article.get("source_type")
        or article.get("source_type_hint")
        or raw.get("source_type")
        or raw.get("source_type_hint")
        or ""
    ).strip().lower()

def _background_flags_for_date_failure(
    article: dict,
    status: str,
    parsed_date: str | None,
    run_date: str,
    date_window: dict,
) -> tuple[bool, str | None, str | None, list[str]]:
    """Compatibility wrapper for freshness policy callers/tests."""
    return background_flags_for_date_failure(article, status, parsed_date, run_date, date_window)


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
        "corroboration": {},
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
            corroboration = record.get("corroboration_level", "none")
            stats["corroboration"][corroboration] = stats["corroboration"].get(corroboration, 0) + 1
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
                   platform_companies: list[str] = None,
                   accepted_articles: list[dict] | None = None) -> dict:
    """Verify a single article. Returns article with verification fields set."""
    blocklist = pipeline_config.get("blocklist", {})
    low_priority = set(pipeline_config.get("low_priority_domains", []))
    magnitude_rules = pipeline_config.get("magnitude_rules", {})
    date_window = pipeline_config.get("date_window", {})
    seen_urls = set() if seen_urls is None else seen_urls
    seen_titles = {} if seen_titles is None else seen_titles
    platform_companies = platform_companies or []
    accepted_articles = [] if accepted_articles is None else accepted_articles

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

    acceptance = EvidenceAcceptancePolicy(
        blocklist=blocklist,
        low_priority_domains=low_priority,
        magnitude_rules=magnitude_rules,
        platform_companies=platform_companies,
    ).evaluate(
        article,
        seen_urls=seen_urls,
        seen_titles=seen_titles,
        accepted_articles=accepted_articles,
    )
    if not acceptance.accepted:
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = acceptance.rejection_reason
        if acceptance.magnitude_flags:
            verified["magnitude_flags"] = acceptance.magnitude_flags
        return verified

    freshness = FreshnessPolicy(date_window).evaluate(article, run_date)
    verified["published_at"] = freshness.published_at
    verified["date_source"] = freshness.date_source
    verified["date_confidence"] = freshness.date_confidence
    if freshness.quality_flags:
        verified["quality_flags"] = freshness.quality_flags
    if not freshness.passed:
        verified["verification_status"] = "rejected"
        verified["rejection_reason"] = freshness.status
        return verified

    if acceptance.platform_admitted:
        verified["platform_admitted"] = True
        verified["platform_reason"] = acceptance.platform_reason
    if acceptance.magnitude_flags:
        verified["magnitude_flags"] = acceptance.magnitude_flags
    verified["corroboration_score"] = acceptance.corroboration_score
    verified["corroboration_level"] = acceptance.corroboration_level
    if acceptance.corroborating_sources:
        verified["corroborating_sources"] = acceptance.corroborating_sources

    # Track for dedup
    if canonical_url:
        seen_urls.add(canonical_url)
    if title:
        seen_titles[title.lower().strip()] = url

    verified["verification_status"] = "verified"
    verified["rejection_reason"] = None
    accepted_articles.append(verified)

    return verified


def main():
    parser = argparse.ArgumentParser(description="Deterministic article verification")
    parser.add_argument("--input", "-i", help="Input JSON file (enriched results array)")
    parser.add_argument("--output", "-o", help="Output JSONL file")
    parser.add_argument("--stats", help="Output JSON stats sidecar; defaults next to --output")
    parser.add_argument("--date", "-d", required=True, help="Run date (YYYY-MM-DD)")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml")
    parser.add_argument("--stale-days", type=int, help="Override freshness stale_days for this run")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)
    if args.stale_days is not None:
        date_window = dict(pipeline_config.get("date_window", {}) or {})
        date_window["stale_days"] = int(args.stale_days)
        pipeline_config["date_window"] = date_window

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
    accepted_articles: list[dict] = []

    for i, article in enumerate(raw_articles):
        result = verify_article(
            article, args.date, i, pipeline_config,
            seen_urls=seen_urls, seen_titles=seen_titles,
            platform_companies=platform_companies,
            accepted_articles=accepted_articles,
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
