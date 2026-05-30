"""Search engine implementations.

Each engine implements the SearchEngine protocol and handles its own API specifics.
Engines are stateless — API keys are passed per-call from the executor.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import re
from typing import Optional

import requests

from stratum.subsystems.search.models import SearchResult, normalize_include_domains


class SearchEngine(ABC):
    """Protocol for a search engine."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine identifier: 'bocha', 'tavily', etc."""
        ...

    @abstractmethod
    def search(self, query: str, locale: str, query_id: str, **kwargs) -> list[SearchResult]:
        """Execute a single search. Returns list of SearchResult (may be empty on failure)."""
        ...


class BochaEngine(SearchEngine):
    """Bocha search API — best for zh-CN, zh-TW queries."""

    name = "bocha"
    supports_include_domains = False

    def __init__(self, api_key: str, freshness: str = "oneDay", count: int = 10):
        self.api_key = api_key
        self.freshness = freshness
        self.count = count

    def search(self, query: str, locale: str, query_id: str, **kwargs) -> list[SearchResult]:
        try:
            date = kwargs.get("date")
            freshness = f"{date}..{date}" if date else self.freshness
            resp = requests.post(
                "https://api.bocha.cn/v1/web-search",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "freshness": freshness, "count": self.count},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("webPages", {}).get("value", [])
            return [SearchResult.from_bocha(item, locale, query_id) for item in items]
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                raise RateLimitedError(f"Bocha rate limited: {query[:50]}")
            raise
        except Exception:
            raise


class TavilyEngine(SearchEngine):
    """Tavily search API — general-purpose, supports domain filtering."""

    name = "tavily"
    supports_include_domains = True

    def __init__(self, api_key: str, search_depth: str = "advanced", max_results: int = 10,
                 include_domains: Optional[dict[str, list[str]]] = None,
                 topic: str = "news",
                 topic_by_intent: Optional[dict[str, str]] = None,
                 topic_by_dimension: Optional[dict[str, str]] = None):
        self.api_key = api_key
        self.search_depth = search_depth
        self.max_results = max_results
        self.include_domains = {
            str(locale): normalize_include_domains(domains)
            for locale, domains in (include_domains or {}).items()
        }
        self.topic = topic
        self.topic_by_intent = topic_by_intent or {}
        self.topic_by_dimension = topic_by_dimension or {}

    @staticmethod
    def _date_window(date: str) -> tuple[str, str]:
        start = datetime.strptime(date, "%Y-%m-%d").date()
        return start.isoformat(), (start + timedelta(days=1)).isoformat()

    @staticmethod
    def _extract_site_filters(query: str) -> tuple[str, list[str]]:
        """Convert site:example.com terms to Tavily include_domains filters."""
        domains = re.findall(r"\bsite:([^\s)]+)", query)
        cleaned = re.sub(r"\bsite:[^\s)]+", " ", query)
        cleaned = re.sub(r"\bOR\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or query, domains

    def _topic_for_query(self, include_domains: list[str], intent: str, dimension: str) -> str:
        """Choose Tavily topic from the query shape and configured strategy."""
        if include_domains:
            return "general"
        if dimension in self.topic_by_dimension:
            return self.topic_by_dimension[dimension]
        if intent in self.topic_by_intent:
            return self.topic_by_intent[intent]
        return self.topic

    @staticmethod
    def _locale_candidates(locale: str) -> list[str]:
        """Return locale config keys from most to least specific."""
        parts = [part for part in (locale or "").split("-") if part]
        if not parts:
            return []

        language = parts[0].lower()
        normalized_parts = [language]
        region = ""
        for part in parts[1:]:
            if len(part) == 2 and part.isalpha():
                normalized = part.upper()
                region = normalized
            elif len(part) == 4 and part.isalpha():
                normalized = part.title()
            else:
                normalized = part
            normalized_parts.append(normalized)

        candidates = [locale, "-".join(normalized_parts)]
        if region:
            candidates.append(f"{language}-{region}")
        candidates.append(language)

        unique_candidates: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            unique_candidates.append(candidate)
        return unique_candidates

    def _include_domains_for_locale(self, locale: str) -> list[str]:
        """Return include domains for exact or compatible locale variants."""
        domains: list[str] = []
        for candidate in self._locale_candidates(locale):
            domains.extend(self.include_domains.get(candidate, []))
        return list(dict.fromkeys(domains))

    def search(self, query: str, locale: str, query_id: str, **kwargs) -> list[SearchResult]:
        date = kwargs.get("date")
        intent = kwargs.get("intent", "detection")
        dimension = kwargs.get("dimension", "general")
        query_domains = normalize_include_domains(kwargs.get("include_domains") or [])
        cleaned_query, site_domains = self._extract_site_filters(query)
        include_domains = list(dict.fromkeys(
            self._include_domains_for_locale(locale)
            + query_domains
            + normalize_include_domains(site_domains)
        ))
        payload: dict = {
            "query": cleaned_query,
            "api_key": self.api_key,
            "search_depth": self.search_depth,
            "max_results": self.max_results,
            "topic": self._topic_for_query(include_domains, intent, dimension),
        }
        if date:
            payload["start_date"], payload["end_date"] = self._date_window(date)

        if include_domains:
            payload["include_domains"] = include_domains

        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("results", [])
            return [SearchResult.from_tavily(item, locale, query_id) for item in items]
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                raise RateLimitedError(f"Tavily rate limited: {query[:50]}")
            if e.response is not None:
                raise requests.HTTPError(
                    f"Tavily HTTP {e.response.status_code}: {e.response.text[:300]}",
                    response=e.response,
                ) from e
            raise
        except Exception:
            raise


class RateLimitedError(Exception):
    """Raised when engine returns 429 — trigger retry/backoff."""
    pass


def create_engines(engine_configs: dict, api_keys: dict) -> dict[str, SearchEngine]:
    """Factory: create engine instances from domain.yaml config."""
    engines: dict[str, SearchEngine] = {}

    if "bocha" in engine_configs and api_keys.get("bocha"):
        cfg = engine_configs["bocha"]
        engines["bocha"] = BochaEngine(
            api_key=api_keys.get("bocha", ""),
            freshness=cfg.get("freshness", "oneDay"),
            count=cfg.get("count", 10),
        )

    if "tavily" in engine_configs and api_keys.get("tavily"):
        cfg = engine_configs["tavily"]
        engines["tavily"] = TavilyEngine(
            api_key=api_keys.get("tavily", ""),
            search_depth=cfg.get("search_depth", "advanced"),
            max_results=cfg.get("max_results", 10),
            include_domains=cfg.get("include_domains", {}),
            topic=cfg.get("topic", "news"),
            topic_by_intent=cfg.get("topic_by_intent", {}),
            topic_by_dimension=cfg.get("topic_by_dimension", {}),
        )

    return engines
