"""Search subsystem data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
    "source",
}


def canonicalize_url(url: str) -> str:
    """Return a stable URL key for deduping search results."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        scheme = (parsed.scheme or "https").lower()
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
        query_items = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            key_lower = key.lower()
            if key_lower in TRACKING_QUERY_KEYS:
                continue
            if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
                continue
            query_items.append((key, value))
        query = urlencode(sorted(query_items))
        return urlunparse((scheme, host, path, "", query, ""))
    except Exception:
        return url.strip()


def source_pattern_matches(url: str, pattern: str) -> bool:
    """Return whether a source-classification pattern matches URL boundaries.

    Dotted patterns are treated as domains with optional path prefixes, so
    `reuters.com` matches `www.reuters.com` and `asia.reuters.com` but not
    `notreuters.com`. Non-domain labels are kept as substring fallbacks for
    configured publisher names that are not host-like.
    """
    pattern = (pattern or "").strip().lower()
    if not url or not pattern:
        return False

    url_lower = url.lower()
    parsed = urlparse(url_lower)
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]

    if "." not in pattern and "/" not in pattern:
        return pattern in url_lower

    pattern_url = pattern if "://" in pattern else f"https://{pattern}"
    parsed_pattern = urlparse(pattern_url)
    pattern_host = parsed_pattern.netloc or parsed_pattern.path.split("/", 1)[0]
    pattern_path = parsed_pattern.path
    if not parsed_pattern.netloc and "/" in parsed_pattern.path:
        _host, _, rest = parsed_pattern.path.partition("/")
        pattern_path = f"/{rest}" if rest else ""

    pattern_host = pattern_host.lower()
    if pattern_host.startswith("www."):
        pattern_host = pattern_host[4:]
    if pattern_host.startswith("m."):
        pattern_host = pattern_host[2:]

    if not pattern_host:
        return pattern in url_lower

    host_matches = host == pattern_host or host.endswith(f".{pattern_host}")
    if not host_matches:
        return False

    if not pattern_path:
        return True

    if parsed.path.startswith(pattern_path):
        return True

    first_path_part = pattern_path.strip("/").split("/", 1)[0]
    return bool(first_path_part) and (
        host == f"{first_path_part}.{pattern_host}"
        or host.endswith(f".{first_path_part}.{pattern_host}")
    )


def normalize_include_domains(domains) -> list[str]:
    """Normalize engine include-domain filters to host-only values.

    Tavily expects bare domains, while config/DB inputs may drift toward URL-ish
    strings. This helper keeps source-scoped Search strict enough to fail on
    malformed structures and forgiving enough to strip presentation prefixes.
    """
    if not domains:
        return []
    if isinstance(domains, str):
        values = [domains]
    elif isinstance(domains, (list, tuple, set)):
        values = list(domains)
    else:
        raise ValueError("include_domains must be a string or a list of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip().lower()
        if not text:
            continue
        parsed = urlparse(text if "://" in text else f"https://{text}")
        host = parsed.netloc or parsed.path.split("/", 1)[0]
        host = host.strip().strip(".")
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        if (
            not host
            or "." not in host
            or ":" in host
            or any(char.isspace() for char in host)
            or "/" in host
        ):
            raise ValueError(f"invalid include_domains value: {value!r}")
        if host not in seen:
            seen.add(host)
            normalized.append(host)
    return normalized


@dataclass
class Query:
    """A search query from domain.yaml or DB."""
    id: str
    text: str
    locale: str
    intent: str = "detection"
    dimension: str = "general"
    include_domains: list[str] = field(default_factory=list)

    def with_substitutions(self, date_str: str) -> "Query":
        """Substitute date variables in query text."""
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        text = self.text
        text = text.replace("${CURRENT_YEAR}", str(dt.year))
        text = text.replace("${CURRENT_MONTH_EN}", dt.strftime("%B"))
        text = text.replace("${CURRENT_MONTH_ZH}", f"{dt.month}月")
        return Query(
            id=self.id,
            text=text,
            locale=self.locale,
            intent=self.intent,
            dimension=self.dimension,
            include_domains=list(self.include_domains),
        )


@dataclass
class SearchResult:
    """A single search result from any engine, normalized to common shape."""
    url: str
    title: str
    snippet: str
    locale: str
    published_at: Optional[str] = None
    source_domain: str = ""
    source_type_hint: str = "media"
    engine: str = ""
    query_id: str = ""
    query_dimension: str = "general"
    score: float = 0.0
    canonical_url: str = ""

    def with_domain(self) -> "SearchResult":
        """Extract domain from URL and set source_domain."""
        parsed = urlparse(self.url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        self.source_domain = host
        self.canonical_url = canonicalize_url(self.url)
        if not self.url and self.canonical_url:
            self.url = self.canonical_url
        return self

    def with_source_hint(self, classifications: dict[str, list[str]]) -> "SearchResult":
        """Classify source type from domain.yaml classification rules."""
        for src_type, domains in classifications.items():
            for d in domains:
                if source_pattern_matches(self.url, d):
                    self.source_type_hint = src_type
                    return self
        return self

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "canonical_url": self.canonical_url or canonicalize_url(self.url),
            "title": self.title,
            "snippet": self.snippet,
            "description": self.snippet,
            "datePublished": self.published_at or "",
            "locale": self.locale,
            "published_at": self.published_at,
            "source_domain": self.source_domain,
            "source_type_hint": self.source_type_hint,
            "engine": self.engine,
            "query_id": self.query_id,
            "query_used": self.query_id,
            "query_dimension": self.query_dimension,
            "score": self.score,
        }

    @classmethod
    def from_bocha(cls, raw: dict, locale: str, query_id: str) -> "SearchResult":
        return cls(
            url=raw.get("url", ""),
            title=raw.get("name", ""),
            snippet=raw.get("snippet", ""),
            locale=locale,
            published_at=raw.get("datePublished"),
            engine="bocha",
            query_id=query_id,
        )

    @classmethod
    def from_tavily(cls, raw: dict, locale: str, query_id: str) -> "SearchResult":
        return cls(
            url=raw.get("url", ""),
            title=raw.get("title", ""),
            snippet=raw.get("content", ""),
            locale=locale,
            published_at=raw.get("published_date"),
            engine="tavily",
            query_id=query_id,
        )


@dataclass
class QueryStats:
    """Per-query execution statistics for health monitoring."""
    query_id: str
    engine_used: str
    status: str  # success | fallback | failed | rate_limited | no_results
    results_count: int
    locale: str = ""
    intent: str = ""
    dimension: str = "general"
    query_text: str = ""
    include_domains: list[str] = field(default_factory=list)
    retries: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        data = {
            "query_id": self.query_id,
            "engine_used": self.engine_used,
            "status": self.status,
            "results_count": self.results_count,
            "locale": self.locale,
            "intent": self.intent,
            "dimension": self.dimension,
            "query_text": self.query_text,
            "retries": self.retries,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }
        if self.include_domains:
            data["include_domains"] = list(self.include_domains)
        return data


@dataclass
class ResultSet:
    """Complete search output: curated results + statistics."""
    results: list[SearchResult] = field(default_factory=list)
    stats: list[QueryStats] = field(default_factory=list)
    date: str = ""
    total_raw: int = 0
    total_curated: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_raw_json(self) -> list[dict]:
        return [r.to_dict() for r in self.results]

    def to_stats_json(self) -> dict:
        return {
            "date": self.date,
            "total_raw": self.total_raw,
            "total_curated": self.total_curated,
            "by_engine": self._count_by("engine"),
            "by_locale": self._count_by("locale"),
            "by_source_type": self._count_by("source_type_hint"),
            "diagnostics": self.diagnostics,
            "queries": self._query_stats_json(),
        }

    def _count_by(self, attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            val = getattr(r, attr, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts

    def _query_stats_json(self) -> list[dict]:
        if self.stats:
            return [s.to_dict() for s in self.stats]

        grouped: dict[tuple[str, str, str, str], int] = {}
        for result in self.results:
            key = (
                result.query_id or "unknown",
                result.engine or "unknown",
                result.locale or "",
                result.query_dimension or "general",
            )
            grouped[key] = grouped.get(key, 0) + 1

        return [
            QueryStats(
                query_id=query_id,
                engine_used=engine,
                status="success",
                results_count=count,
                locale=locale,
                dimension=dimension,
            ).to_dict()
            for (query_id, engine, locale, dimension), count in sorted(grouped.items())
        ]
