#!/usr/bin/env python3
"""normalize.py — Deterministic article normalization.

Domain-agnostic. All classification rules, entities, and terms loaded from domain.yaml.

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

CST = timezone(timedelta(hours=8))


def load_domain_config(domain_path: str) -> dict:
    """Load pipeline section from domain.yaml."""
    with open(domain_path) as f:
        config = yaml.safe_load(f)
    return config.get("pipeline", {})


def extract_domain(url: str) -> str:
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


def classify_source_type(url: str, source_classification: dict) -> str:
    """Classify source_type based on domain. Uses injected classification rules."""
    domain = extract_domain(url)

    for category, patterns in source_classification.items():
        for pattern in patterns:
            if pattern in domain or pattern in url.lower():
                return category

    # Default heuristic
    if any(tld in domain for tld in [".com", ".co.jp", ".jp", ".cn", ".tw", ".kr"]):
        return "media"

    return "unknown"


def classify_artifact_type(title: str, snippet: str, artifact_types: dict) -> str:
    """Classify artifact type from title and snippet using domain patterns."""
    text = f"{title} {snippet}".lower()

    for artifact_type, config in artifact_types.items():
        pattern = config.get("pattern", "")
        if pattern and re.search(pattern, text):
            return artifact_type

    return "news_article"


def extract_entities(title: str, snippet: str, flat_entities: list[str]) -> list[str]:
    """Extract known entities from title and snippet."""
    text = f"{title} {snippet}"
    found = []
    for entity in flat_entities:
        if entity.lower() in text.lower():
            if entity not in found:
                found.append(entity)
    return found


def extract_terms(title: str, snippet: str, flat_terms: list[str]) -> list[str]:
    """Extract known technical terms from title and snippet."""
    text = f"{title} {snippet}".lower()
    found = []
    for term in flat_terms:
        if term.lower() in text:
            if term not in found:
                found.append(term)
    return found


def extract_numeric_claims(snippet: str, numeric_patterns: list[str]) -> list[str]:
    """Extract numeric claims with context."""
    claims = []
    for pattern in numeric_patterns:
        matches = re.findall(pattern, snippet, re.IGNORECASE)
        claims.extend(matches)
    return list(dict.fromkeys(claims))


def content_hash(url: str, title: str) -> str:
    """SHA-256 of url+title for dedup."""
    return hashlib.sha256(f"{url}{title}".encode()).hexdigest()


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


def normalize_article(article: dict, pipeline_config: dict, index: int) -> Optional[dict]:
    """Normalize a verified article using domain config."""
    if article.get("verification_status") != "verified":
        return None

    source_classification = pipeline_config.get("source_classification", {})
    artifact_types = pipeline_config.get("artifact_types", {})
    flat_entities = pipeline_config.get("flat_entities", [])
    flat_terms = pipeline_config.get("flat_terms", [])
    numeric_patterns = pipeline_config.get("numeric_patterns", [])
    locale_rules = pipeline_config.get("locale_rules", {})

    url = article.get("url", "")
    title = article.get("title", "")
    snippet = article.get("snippet", "")
    published_at = article.get("published_at", "")
    source = article.get("source", extract_domain(url))
    query_used = article.get("query_used", "")

    obj_id = hashlib.sha256(f"{url}{title}".encode()).hexdigest()[:16]

    return {
        "id": obj_id,
        "url": url,
        "canonical_url": url,
        "title": title,
        "source": source,
        "source_type": classify_source_type(url, source_classification),
        "source_locale": determine_source_locale(url, locale_rules),
        "published_at": published_at,
        "fetched_at": datetime.now(CST).isoformat(),
        "snippet": snippet,
        "extracted_summary": snippet[:300] if snippet else "",
        "content_hash": content_hash(url, title),
        "entities": extract_entities(title, snippet, flat_entities),
        "terms": extract_terms(title, snippet, flat_terms),
        "numeric_claims": extract_numeric_claims(snippet, numeric_patterns),
        "verification_status": "verified",
        "rejection_reason": None,
        "discovery_mode": "baseline_seed",
        "artifact_type": classify_artifact_type(title, snippet, artifact_types),
        "cluster_id": None,
        "event_thread_id": None,
    }


def main():
    parser = argparse.ArgumentParser(description="Deterministic article normalization")
    parser.add_argument("--input", "-i", required=True, help="Input verified.jsonl")
    parser.add_argument("--output", "-o", required=True, help="Output articles.jsonl")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)

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
        norm = normalize_article(article, pipeline_config, i)
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
