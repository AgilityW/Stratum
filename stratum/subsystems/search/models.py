"""Search subsystem data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Query:
    """A search query from domain.yaml or DB."""
    id: str
    text: str
    locale: str
    intent: str = "detection"

    def with_substitutions(self, date_str: str) -> "Query":
        """Substitute date variables in query text."""
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        text = self.text
        text = text.replace("${CURRENT_YEAR}", str(dt.year))
        text = text.replace("${CURRENT_MONTH_EN}", dt.strftime("%B"))
        text = text.replace("${CURRENT_MONTH_ZH}", f"{dt.month}月")
        return Query(id=self.id, text=text, locale=self.locale, intent=self.intent)


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
    score: float = 0.0

    def with_domain(self) -> "SearchResult":
        """Extract domain from URL and set source_domain."""
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        self.source_domain = parsed.netloc.lower().lstrip("www.")
        return self

    def with_source_hint(self, classifications: dict[str, list[str]]) -> "SearchResult":
        """Classify source type from domain.yaml classification rules."""
        url_lower = self.url.lower()
        for src_type, domains in classifications.items():
            for d in domains:
                if d in url_lower:
                    self.source_type_hint = src_type
                    return self
        return self

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "locale": self.locale,
            "published_at": self.published_at,
            "source_domain": self.source_domain,
            "source_type_hint": self.source_type_hint,
            "engine": self.engine,
            "query_id": self.query_id,
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
    status: str  # success | fallback | failed | rate_limited
    results_count: int
    retries: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "query_id": self.query_id,
            "engine_used": self.engine_used,
            "status": self.status,
            "results_count": self.results_count,
            "retries": self.retries,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }


@dataclass
class ResultSet:
    """Complete search output: curated results + statistics."""
    results: list[SearchResult] = field(default_factory=list)
    stats: list[QueryStats] = field(default_factory=list)
    date: str = ""
    total_raw: int = 0
    total_curated: int = 0

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
            "queries": [s.to_dict() for s in self.stats],
        }

    def _count_by(self, attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            val = getattr(r, attr, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts
