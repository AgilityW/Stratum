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
    """Extract known technical terms from title and snippet (Source 1: static list)."""
    text = f"{title} {snippet}".lower()
    found = []
    for term in flat_terms:
        if term.lower() in text:
            if term not in found:
                found.append(term)
    return found


def extract_title_patterns(title: str) -> list[str]:
    """Extract discriminative terms from title (Source 2: pattern extraction).

    Captures: company names, product codes, numbers with units.
    Avoids generic stopwords that appear in every storage article.
    """
    if not title:
        return []

    patterns = [
        # Product codes: HBM4E, DDR5, NAND, 3D NAND, PCIe Gen6
        r'\b[A-Z]{2,}[-\s]?[A-Za-z]*[0-9]*[A-Za-z]*\b',
        # Numbers with units: 12层, 48GB, 295亿, 20%
        r'\d+\s*(?:层|GB|TB|亿|万|％|%|nm|Mbps|Gbps)',
        # Chinese company/entity names: 长鑫科技, 长江存储, 三星电子
        r'[\u4e00-\u9fff]{2,}(?:存储|科技|电子|半导体|芯片|内存|闪存|海力士|美光|铠侠)',
    ]

    # Generic stopwords — these appear in almost every storage article
    stopwords = {
        "半导体", "存储", "内存", "芯片", "NAND", "DRAM", "SSD", "HBM",
        "闪存", "涨价", "价格", "市场", "全球", "产业",
    }

    found = []
    text = title
    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            m = match.strip()
            if m.lower() not in {s.lower() for s in stopwords} and m not in found:
                found.append(m)

    return found


def load_thread_keywords(path: str) -> dict:
    """Load thread_keywords.json, return empty if missing."""
    if not path or not os.path.exists(path):
        return {"threads": []}
    with open(path) as f:
        return json.load(f)


def match_thread_keywords(title: str, snippet: str, thread_keywords: dict) -> tuple[Optional[str], list[str]]:
    """Match article against active event threads (Source 3: thread_keywords).

    IDF-weighted co-occurrence scoring — an event is defined by its keyword
    fingerprint, not just any single keyword:
      - IDF weight: keyword in 1 thread = ×2, in 2-3 = ×1, in 4+ = ×0.5
      - Co-occurrence bonus: +2 per additional keyword matched (same thread)
      - Full keyword: 3 × IDF, Topic: 2 × IDF, CJK sub-token: 1
      - Threshold: score ≥ 3 if strong signal present; ≥ 4 if CJK-only

    Highest-scoring thread wins; ties broken by thread order.

    Returns (thread_id | None, additional_keywords | []).
    """
    text = f"{title} {snippet}".lower()

    # ── Precompute IDF: count how many threads each keyword appears in ──
    kw_thread_count = {}
    threads_list = thread_keywords.get("threads", [])
    for thread in threads_list:
        seen_in_thread = set()
        for kw in thread.get("keywords", []):
            k = kw.lower().strip()
            if k and k not in seen_in_thread:
                kw_thread_count[k] = kw_thread_count.get(k, 0) + 1
                seen_in_thread.add(k)

    def idf_weight(kw: str) -> float:
        count = kw_thread_count.get(kw, 1)
        if count == 1:
            return 2.0   # Unique to one thread — highly specific
        elif count <= 3:
            return 1.0   # Moderate overlap
        else:
            return 0.5   # Generic — appears in 4+ threads

    best_score = 0
    best_tid = None
    best_tokens = []

    for thread in threads_list:
        keywords = [k.lower().strip() for k in thread.get("keywords", []) if k.strip()]
        topics = [t.lower().strip() for t in thread.get("topics", []) if t.strip()]

        score = 0.0
        strong_signals = 0
        matched_kw_count = 0  # For co-occurrence bonus

        # Full keyword matches (weight 3 × IDF, counts as strong only if
        # unique to thread OR co-occurring with other keywords)
        for kw in keywords:
            if len(kw) >= 2 and kw in text:
                w = idf_weight(kw)
                score += 3 * w
                matched_kw_count += 1
                # Strong signal: unique keyword (IDF≥2) or part of co-occurrence
                if w >= 2.0:
                    strong_signals += 1

        # Topic matches (weight 2 × IDF, strong)
        for tp in topics:
            if len(tp) >= 2 and tp in text:
                score += 2 * idf_weight(tp)
                strong_signals += 1

        # ASCII words extracted from compound keywords (weight 2, strong)
        kw_text = ' '.join(keywords)
        ascii_words = re.findall(r'[A-Za-z0-9]{2,}', kw_text)
        seen_ascii = set(k.lower() for k in keywords if k.isascii())
        for w in ascii_words:
            wl = w.lower()
            if wl not in seen_ascii and wl in text:
                score += 2
                strong_signals += 1
                matched_kw_count += 1

        # CJK sub-token matches from compound phrases (weight 1, weak)
        cjk_seen = set()
        for kw in keywords:
            cjk_chars = re.findall(r'[\u4e00-\u9fff]', kw)
            if len(cjk_chars) <= 2:
                continue
            for win_size in (2, 3, 4):
                for i in range(len(cjk_chars) - win_size + 1):
                    sub = ''.join(cjk_chars[i:i + win_size])
                    if sub not in cjk_seen and len(sub) >= 2 and sub in text:
                        score += 1
                        cjk_seen.add(sub)

        # Co-occurrence bonus: +2 per additional keyword matched
        if matched_kw_count >= 2:
            score += (matched_kw_count - 1) * 2
            strong_signals = max(strong_signals, 1)  # co-occurrence IS a strong signal

        # Two-tier threshold
        threshold = 3 if strong_signals > 0 else 4
        if score >= threshold and score > best_score:
            best_score = score
            best_tid = thread.get("thread_id")
            best_tokens = keywords + topics

    return best_tid, best_tokens


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
    numeric_patterns = pipeline_config.get("numeric_patterns", [])
    locale_rules = pipeline_config.get("locale_rules", {})

    url = article.get("url", "")
    title = article.get("title", "")
    snippet = article.get("snippet", "")
    published_at = article.get("published_at", "")
    source = article.get("source", extract_domain(url))
    query_used = article.get("query_used", "")

    obj_id = hashlib.sha256(f"{url}{title}".encode()).hexdigest()[:16]

    # ── Three-source term extraction (v5.1) ──
    # Source 1: static domain.yaml flat_terms
    base_terms = extract_terms(title, snippet, flat_terms)
    # Source 2: title pattern extraction
    title_terms = extract_title_patterns(title)
    # Source 3: thread_keywords matching
    thread_id, thread_terms = match_thread_keywords(title, snippet, thread_keywords)
    # Merge: static + title_patterns + thread_terms, deduplicate
    all_terms = list(dict.fromkeys(base_terms + title_terms + thread_terms))

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
        "terms": all_terms,
        "numeric_claims": extract_numeric_claims(snippet, numeric_patterns),
        "verification_status": "verified",
        "rejection_reason": None,
        "discovery_mode": "baseline_seed",
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
