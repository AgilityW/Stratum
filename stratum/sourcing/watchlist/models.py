"""Watchlist acquisition contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from stratum.sourcing.discovery import SearchResult


@dataclass
class WatchlistSourceStats:
    """Per-source source health record for monitoring."""

    source: str
    access: str
    status: str
    hits: int
    duration_ms: float
    locale: str = ""
    category: str = ""
    dated: int = 0
    selected: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WatchlistRun:
    """Watchlist results plus structured source-level health."""

    results: list[SearchResult]
    source_stats: list[WatchlistSourceStats]
    observations: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def stats_json(self, domain: str, run_date: str) -> dict[str, Any]:
        return {
            "domain": domain,
            "date": run_date,
            "total_results": len(self.results),
            "sources": [s.to_dict() for s in self.source_stats],
        }


@dataclass
class WatchlistChannelResult:
    """One source acquisition result from a concrete watchlist channel."""

    results: list[SearchResult]
    access: str
    status: str
    locale: str = ""
    category: str = ""
    error: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)


# Backward-compatible names for callers that still import the old collector API.
CollectorSourceStats = WatchlistSourceStats
CollectorRun = WatchlistRun
CollectorChannelResult = WatchlistChannelResult
