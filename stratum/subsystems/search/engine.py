"""Search engine implementations.

Each engine implements the SearchEngine protocol and handles its own API specifics.
Engines are stateless — API keys are passed per-call from the executor.
"""

import time
from abc import ABC, abstractmethod
from typing import Optional

import requests

from stratum.subsystems.search.models import SearchResult


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

    def __init__(self, api_key: str, freshness: str = "oneDay", count: int = 10):
        self.api_key = api_key
        self.freshness = freshness
        self.count = count

    def search(self, query: str, locale: str, query_id: str, **kwargs) -> list[SearchResult]:
        try:
            resp = requests.post(
                "https://api.bocha.cn/v1/web-search",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "freshness": self.freshness, "count": self.count},
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

    def __init__(self, api_key: str, search_depth: str = "advanced", max_results: int = 10,
                 include_domains: Optional[dict[str, list[str]]] = None):
        self.api_key = api_key
        self.search_depth = search_depth
        self.max_results = max_results
        self.include_domains = include_domains or {}

    def search(self, query: str, locale: str, query_id: str, **kwargs) -> list[SearchResult]:
        payload: dict = {
            "query": query,
            "api_key": self.api_key,
            "search_depth": self.search_depth,
            "max_results": self.max_results,
        }

        if locale in self.include_domains:
            payload["include_domains"] = self.include_domains[locale]

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
            raise
        except Exception:
            raise


class RateLimitedError(Exception):
    """Raised when engine returns 429 — trigger retry/backoff."""
    pass


def create_engines(engine_configs: dict, api_keys: dict) -> dict[str, SearchEngine]:
    """Factory: create engine instances from domain.yaml config."""
    engines: dict[str, SearchEngine] = {}

    if "bocha" in engine_configs:
        cfg = engine_configs["bocha"]
        engines["bocha"] = BochaEngine(
            api_key=api_keys.get("bocha", ""),
            freshness=cfg.get("freshness", "oneDay"),
            count=cfg.get("count", 10),
        )

    if "tavily" in engine_configs:
        cfg = engine_configs["tavily"]
        engines["tavily"] = TavilyEngine(
            api_key=api_keys.get("tavily", ""),
            search_depth=cfg.get("search_depth", "advanced"),
            max_results=cfg.get("max_results", 10),
            include_domains=cfg.get("include_domains", {}),
        )

    return engines
