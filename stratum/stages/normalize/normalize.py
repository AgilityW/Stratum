#!/usr/bin/env python3
"""normalize.py — Deterministic article normalization.

Domain-agnostic. All classification rules, entities, terms loaded from domain.yaml.

Input:  JSONL — verified articles with {verification_status, url, title, snippet, published_at, ...}
Output: JSONL — normalized ArticleRecords with {source_type, source_locale, entities, terms, content_hash, ...}
Side effects: None. Pure function — reads input + domain.yaml, writes output.
Invariants:  Filters verification_status != "verified" (rejected articles silently dropped).
             SHA-256 dedup: same url+title → first occurrence kept, subsequent ones dropped.
Error behavior: Non-verified records → skipped (not written to output). Missing fields → empty defaults.

Usage:
    python3 normalize.py --input verified.jsonl --output articles.jsonl \
        --domain domains/storage/domain.yaml
"""
import argparse
import hashlib
import json
import os
import re
import sys
import yaml
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

from stratum.sourcing.discovery import canonicalize_url, source_pattern_matches
try:
    from .extractors import (
        ClaimExtractor,
        EntityResolver,
        TermResolver,
    )
    from .thread_matcher import ThreadKeywordMatcher
except ImportError:  # pragma: no cover - direct script/test fallback
    from stratum.stages.normalize.extractors import (
        ClaimExtractor,
        EntityResolver,
        TermResolver,
    )
    from stratum.stages.normalize.thread_matcher import ThreadKeywordMatcher

CST = timezone(timedelta(hours=8))

CANONICAL_SOURCE_TYPES = {"official", "analyst", "media", "blog", "social", "unknown"}
SOURCE_TYPE_ALIASES = {
    "newsroom": "official",
    "press": "official",
    "press_release": "official",
    "press-release": "official",
    "rss": "media",
    "news": "media",
}


def load_domain_config(domain_path: str) -> dict:
    """Load pipeline section from domain.yaml."""
    with open(domain_path) as f:
        config = yaml.safe_load(f) or {}
    pipeline = dict(config.get("pipeline", {}))
    pipeline["entity_records"] = list(config.get("companies", []) or []) + list(pipeline.get("flat_entities", []) or [])
    pipeline["term_records"] = list(config.get("terms", []) or []) + list(pipeline.get("flat_terms", []) or [])
    return pipeline


def extract_domain(url: str) -> str:
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


def normalize_source_type(value: str) -> str:
    """Normalize upstream source hints into ArticleRecord source_type values."""
    normalized = SOURCE_TYPE_ALIASES.get((value or "").strip().lower(), (value or "").strip().lower())
    if normalized in CANONICAL_SOURCE_TYPES:
        return normalized
    return ""


def classify_source_type(url: str, source_classification: dict) -> str:
    """Classify source_type based on domain. Uses injected classification rules."""
    domain = extract_domain(url)

    for category, patterns in source_classification.items():
        for pattern in patterns:
            if source_pattern_matches(url, pattern):
                return category

    # Default heuristic
    if any(tld in domain for tld in [".com", ".co.jp", ".jp", ".cn", ".tw", ".kr"]):
        return "media"

    return "unknown"


def resolve_source_type(article: dict, url: str, source_classification: dict) -> str:
    """Prefer upstream source typing, then fall back to domain classification."""
    raw_metadata = article.get("raw_metadata", {})
    explicit = (
        article.get("source_type")
        or article.get("source_type_hint")
        or raw_metadata.get("source_type")
        or raw_metadata.get("source_type_hint")
    )
    normalized = normalize_source_type(explicit)
    if normalized:
        return normalized
    return classify_source_type(url, source_classification)


def classify_artifact_type(title: str, snippet: str, artifact_types: dict) -> str:
    """Classify artifact type from title and snippet using domain patterns."""
    text = f"{title} {snippet}".lower()

    for artifact_type, config in artifact_types.items():
        pattern = config.get("pattern", "")
        if pattern and re.search(pattern, text):
            return artifact_type

    return "news_article"


def load_thread_keywords(path: str) -> dict:
    """Load thread_keywords.json, return empty if missing."""
    if not path or not os.path.exists(path):
        return {"threads": []}
    with open(path) as f:
        return json.load(f)


def content_hash(url: str, title: str) -> str:
    """SHA-256 of canonical URL + title for dedup."""
    url_key = canonicalize_url(url) or url
    return hashlib.sha256(f"{url_key}{title}".encode()).hexdigest()


def determine_source_locale(url: str, locale_rules: dict) -> str:
    """Guess locale from URL patterns (OR logic: pattern match OR keyword match)."""
    domain = extract_domain(url)
    domain_patterns = locale_rules.get("domain_patterns", [])

    for rule in domain_patterns:
        pattern = rule.get("pattern", "")
        keywords = rule.get("keywords", [])

        # Match if pattern is in domain OR any keyword is in domain
        pattern_match = pattern in domain
        keyword_match = any(kw in domain for kw in keywords) if keywords else False

        if pattern_match or keyword_match:
            return rule.get("locale", "en")

    return locale_rules.get("default_locale", "en")


def resolve_source_locale(article: dict, url: str, locale_rules: dict) -> str:
    """Prefer explicit upstream locale, then fall back to URL heuristics."""
    explicit = article.get("locale") or article.get("raw_metadata", {}).get("locale")
    if explicit:
        return explicit
    return determine_source_locale(url, locale_rules)


def normalize_article(article: dict, pipeline_config: dict, index: int,
                     thread_keywords: dict = None) -> Optional[dict]:
    """Normalize a verified article using domain config.

    Args:
        thread_keywords: Optional thread_keywords.json dict for event matching.
    """
    if thread_keywords is None:
        thread_keywords = {"threads": []}

    if article.get("verification_status") != "verified":
        return None

    source_classification = pipeline_config.get("source_classification", {})
    artifact_types = pipeline_config.get("artifact_types", {})
    flat_entities = pipeline_config.get("flat_entities", [])
    flat_terms = pipeline_config.get("flat_terms", [])
    entity_records = pipeline_config.get("entity_records") or flat_entities
    term_records = pipeline_config.get("term_records") or flat_terms
    numeric_patterns = pipeline_config.get("numeric_patterns", [])
    locale_rules = pipeline_config.get("locale_rules", {})

    url = article.get("url", "")
    canonical_url = article.get("canonical_url") or article.get("raw_metadata", {}).get("canonical_url") or canonicalize_url(url)
    title = article.get("title", "")
    snippet = article.get("snippet", "")
    published_at = article.get("published_at", "")
    date_source = article.get("date_source") or article.get("raw_metadata", {}).get("date_source", "")
    date_confidence = article.get("date_confidence") or article.get("raw_metadata", {}).get("date_confidence", "")
    quality_flags = article.get("quality_flags") or article.get("raw_metadata", {}).get("quality_flags", [])
    source = article.get("source", extract_domain(url))
    query_used = article.get("query_used", "")
    raw_metadata = article.get("raw_metadata", {})
    query_id = article.get("query_id") or raw_metadata.get("query_id") or query_used
    query_dimension = article.get("query_dimension") or raw_metadata.get("query_dimension", "general")
    engine = article.get("engine") or raw_metadata.get("engine", "unknown")
    discovery_mode = article.get("discovery_mode") or raw_metadata.get("discovery_mode", "baseline_seed")

    obj_id = hashlib.sha256(f"{canonical_url or url}{title}".encode()).hexdigest()[:16]

    # ── Three-source term extraction (v5.1) ──
    thread_id, thread_terms = ThreadKeywordMatcher(thread_keywords).match_tuple(title, snippet)
    entity_resolver = EntityResolver(entity_records)
    term_resolver = TermResolver(term_records)
    all_terms = term_resolver.resolve(title, snippet, thread_terms)

    return {
        "id": obj_id,
        "url": url,
        "canonical_url": canonical_url or url,
        "title": title,
        "source": source,
        "source_type": resolve_source_type(article, url, source_classification),
        "source_locale": resolve_source_locale(article, url, locale_rules),
        "published_at": published_at,
        "date_source": date_source,
        "date_confidence": date_confidence,
        "quality_flags": quality_flags,
        "fetched_at": datetime.now(CST).isoformat(),
        "snippet": snippet,
        "extracted_summary": snippet[:300] if snippet else "",
        "content_hash": content_hash(canonical_url or url, title),
        "entities": entity_resolver.resolve(title, snippet),
        "entity_ids": entity_resolver.resolve_ids(title, snippet),
        "terms": all_terms,
        "term_ids": term_resolver.resolve_ids(title, snippet, thread_terms),
        "numeric_claims": ClaimExtractor(numeric_patterns).extract_numeric_claims(snippet),
        "typed_numeric_claims": ClaimExtractor(numeric_patterns).extract_typed_numeric_claims(
            f"{title} {snippet}"
        ),
        "verification_status": "verified",
        "rejection_reason": None,
        "discovery_mode": discovery_mode,
        "engine": engine,
        "query_id": query_id,
        "query_used": query_used,
        "query_dimension": query_dimension,
        "artifact_type": classify_artifact_type(title, snippet, artifact_types),
        "cluster_id": None,
        "event_thread_id": thread_id,
    }


def main():
    parser = argparse.ArgumentParser(description="Deterministic article normalization")
    parser.add_argument("--input", "-i", required=True, help="Input verified.jsonl")
    parser.add_argument("--output", "-o", required=True, help="Output articles.jsonl")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml")
    parser.add_argument("--thread-keywords", default=None,
                        help="Path to thread_keywords.json (optional)")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)
    thread_keywords = load_thread_keywords(args.thread_keywords) if args.thread_keywords else {"threads": []}

    # Load verified articles
    articles = []
    with open(args.input) as f:
        for line in f:
            if line.strip():
                articles.append(json.loads(line))

    # Normalize
    normalized = []
    seen_hashes = set()
    duplicates = 0
    stats = {"total": len(articles), "normalized": 0, "duplicates": 0,
             "source_types": {}, "locales": {}}

    for i, article in enumerate(articles):
        norm = normalize_article(article, pipeline_config, i, thread_keywords)
        if norm is None:
            continue

        h = norm["content_hash"]
        if h in seen_hashes:
            duplicates += 1
            continue
        seen_hashes.add(h)

        normalized.append(norm)
        stats["normalized"] += 1
        stats["source_types"][norm["source_type"]] = \
            stats["source_types"].get(norm["source_type"], 0) + 1
        stats["locales"][norm["source_locale"]] = \
            stats["locales"].get(norm["source_locale"], 0) + 1

    stats["duplicates"] = duplicates

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        for article in normalized:
            f.write(json.dumps(article, ensure_ascii=False) + "\n")

    print(f"\n📊 Normalization complete:", file=sys.stderr)
    print(f"   Total in:    {stats['total']}", file=sys.stderr)
    print(f"   Normalized:  {stats['normalized']}", file=sys.stderr)
    print(f"   Duplicates:  {stats['duplicates']}", file=sys.stderr)
    print(f"   Source types: {stats['source_types']}", file=sys.stderr)
    print(f"   Locales:      {stats['locales']}", file=sys.stderr)


if __name__ == "__main__":
    main()
