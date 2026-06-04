"""Evidence acceptance policy for Verify."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from stratum.sourcing.discovery import canonicalize_url, source_pattern_matches


@dataclass(frozen=True)
class EvidenceAcceptanceDecision:
    """Acceptance gate decision for a single article."""

    accepted: bool
    rejection_reason: str | None = None
    magnitude_flags: list[str] = field(default_factory=list)
    platform_admitted: bool = False
    platform_reason: str = ""
    corroboration_score: float = 0.0
    corroboration_level: str = "none"
    corroborating_sources: list[str] = field(default_factory=list)


class EvidenceAcceptancePolicy:
    """Own non-freshness evidence gates for Verify."""

    def __init__(
        self,
        *,
        blocklist: dict | None = None,
        low_priority_domains: set[str] | list[str] | None = None,
        magnitude_rules: dict | None = None,
        platform_companies: list[str] | None = None,
    ):
        self.blocklist = blocklist or {}
        self.low_priority_domains = set(low_priority_domains or [])
        self.magnitude_rules = magnitude_rules or {}
        self.platform_companies = platform_companies or []

    def evaluate(
        self,
        article: dict,
        *,
        seen_urls: set,
        seen_titles: dict,
        accepted_articles: list[dict] | None = None,
    ) -> EvidenceAcceptanceDecision:
        """Evaluate blocklist, low-priority, magnitude, duplicate, and platform gates."""
        url = article.get("url", "")
        title = article.get("title", "")
        is_blocked, block_reason = is_blocklisted(url, self.blocklist)
        if is_blocked:
            return EvidenceAcceptanceDecision(False, block_reason)

        if is_low_priority_domain(url, self.low_priority_domains):
            return EvidenceAcceptanceDecision(False, "LOW_SIGNAL")

        magnitude_flags = check_magnitude(article, self.magnitude_rules)
        impossible_flags = [flag for flag in magnitude_flags if "IMPOSSIBLE" in flag]
        if impossible_flags:
            return EvidenceAcceptanceDecision(False, impossible_flags[0], magnitude_flags=magnitude_flags)

        is_dup, dup_reason = check_duplicate(url, title, seen_urls, seen_titles)
        if is_dup:
            return EvidenceAcceptanceDecision(False, dup_reason)

        domain = extract_domain(url)
        platform_admitted, platform_reason = check_platform_admission(domain, self.platform_companies)
        corroboration = score_corroboration(article, accepted_articles or [])
        return EvidenceAcceptanceDecision(
            accepted=True,
            magnitude_flags=magnitude_flags,
            platform_admitted=platform_admitted,
            platform_reason=platform_reason,
            corroboration_score=corroboration["score"],
            corroboration_level=corroboration["level"],
            corroborating_sources=corroboration["sources"],
        )


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
    for _category, patterns in blocklist.items():
        for blocked in patterns:
            if source_pattern_matches(url, blocked):
                return True, f"BLOCKED: {blocked}"
    return False, ""


def is_low_priority_domain(url: str, low_priority_domains: set[str]) -> bool:
    """Check whether URL belongs to a low-priority exact domain or subdomain."""
    return any(source_pattern_matches(url, pattern) for pattern in low_priority_domains)


def check_magnitude(article: dict, magnitude_rules: dict) -> list[str]:
    """Check for implausible magnitude claims in snippet/title."""
    flags = []
    text = f"{article.get('title', '')} {article.get('snippet', '')}"

    share_max = magnitude_rules.get("share_max_pct", 100)
    share_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:market\s*)?share", text, re.IGNORECASE)
    if share_match:
        share = float(share_match.group(1))
        if share > share_max:
            flags.append(f"IMPOSSIBLE: market share {share}% > {share_max}%")

    rev_match = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*(?:trillion|T)\b", text, re.IGNORECASE)
    if rev_match:
        rev = float(rev_match.group(1))
        if rev >= 1.0:
            flags.append(f"FLAG: revenue ${rev}T exceeds sanity threshold")

    return flags


def check_duplicate(url: str, title: str, seen_urls: set, seen_titles: dict) -> tuple[bool, str]:
    """Deduplicate by canonical URL or near-duplicate title."""
    canonical_url = canonicalize_url(url)
    if canonical_url and canonical_url in seen_urls:
        return True, "DUPLICATE_URL"
    if title:
        title_lower = title.lower().strip()
        for seen_title, _seen_url in seen_titles.items():
            if title_similarity(title_lower, seen_title) > 0.85:
                return True, f"DUPLICATE_TITLE: similar to '{seen_title[:60]}'"
    return False, ""


def title_similarity(a: str, b: str) -> float:
    """Jaccard-like similarity on character bigrams for CJK-friendly comparison."""

    def bigrams(s: str) -> set:
        return {s[i:i + 2] for i in range(len(s) - 1)}

    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def check_platform_admission(domain: str, platform_companies: list[str]) -> tuple[bool, str]:
    """Return whether a source domain should be marked as platform-admitted."""
    if not platform_companies or not domain:
        return False, ""
    domain_lower = domain.lower()
    for name in platform_companies:
        if name.lower() in domain_lower:
            return True, f"PLATFORM_ADMIT: {name}"
    return False, ""


SOURCE_TYPE_QUALITY = {
    "official": 2.0,
    "financial": 2.0,
    "analyst": 1.5,
    "media": 1.0,
    "blog": 0.5,
    "social": 0.25,
}


def score_corroboration(article: dict, accepted_articles: list[dict]) -> dict:
    """Score whether an article has independent high-quality corroboration."""
    source = article_source_identity(article)
    source_type = article_source_type(article)
    score = SOURCE_TYPE_QUALITY.get(source_type, 0.5)
    corroborating_sources: list[str] = []

    for prior in accepted_articles:
        prior_source = article_source_identity(prior)
        if not prior_source or prior_source == source:
            continue
        if article_similarity(article, prior) < 0.28:
            continue
        if prior_source not in corroborating_sources:
            corroborating_sources.append(prior_source)
        score += 2.0
        score += min(SOURCE_TYPE_QUALITY.get(article_source_type(prior), 0.5), 1.0)

    if score >= 4.0:
        level = "high"
    elif score >= 2.0:
        level = "medium"
    elif score > 0:
        level = "low"
    else:
        level = "none"
    return {
        "score": round(score, 2),
        "level": level,
        "sources": corroborating_sources[:5],
    }


def article_similarity(left: dict, right: dict) -> float:
    """Return a coarse token-overlap similarity for corroboration grouping."""
    left_tokens = evidence_tokens(left)
    right_tokens = evidence_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def evidence_tokens(article: dict) -> set[str]:
    text = f"{article.get('title', '')} {article.get('snippet', '')} {article.get('description', '')}".lower()
    tokens = {
        token.strip(".-")
        for token in re.findall(r"[a-z0-9][a-z0-9+.-]*|[\u4e00-\u9fff]{2,}", text)
    }
    stopwords = {
        "the", "and", "for", "with", "from", "that", "this", "will", "said",
        "news", "report", "reports", "update", "market", "company", "industry",
    }
    return {token for token in tokens if len(token) >= 2 and token not in stopwords}


def article_source_identity(article: dict) -> str:
    raw = article.get("raw_metadata", {}) if isinstance(article.get("raw_metadata"), dict) else {}
    explicit = article.get("source") or article.get("source_domain") or raw.get("source") or raw.get("source_domain")
    if explicit:
        return str(explicit).strip().lower()
    return extract_domain(str(article.get("url") or ""))


def article_source_type(article: dict) -> str:
    raw = article.get("raw_metadata", {}) if isinstance(article.get("raw_metadata"), dict) else {}
    return str(
        article.get("source_type")
        or article.get("source_type_hint")
        or raw.get("source_type")
        or raw.get("source_type_hint")
        or ""
    ).strip().lower()
