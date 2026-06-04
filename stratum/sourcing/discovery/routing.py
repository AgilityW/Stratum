"""Search routing policy algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


HEALTH_RECOMMENDATION_PRIORITY = {
    "healthy": 0,
    "watch": 1,
    "deprioritize": 2,
    "avoid": 3,
}


@dataclass(frozen=True)
class RoutingDecision:
    """Selected engine chain and the reasons that affected it."""

    locale: str
    matched_locale: str | None
    configured_order: list[str]
    selected_order: list[str]
    health_applied: bool


class RoutingPolicy:
    """Choose the engine fallback chain for a query."""

    def __init__(self, routing: dict[str, list[str]], engine_health: dict[str, dict[str, Any]] | None = None):
        self.routing = routing
        self.engine_health = engine_health or {}

    def decide(self, locale: str) -> RoutingDecision:
        """Return the configured route adjusted by persisted engine health."""
        matched_locale, configured_order = self._configured_order(locale)
        selected_order = self._apply_engine_health(configured_order)
        return RoutingDecision(
            locale=locale,
            matched_locale=matched_locale,
            configured_order=list(configured_order),
            selected_order=selected_order,
            health_applied=selected_order != list(configured_order),
        )

    def route(self, locale: str) -> list[str]:
        """Return only the selected engine order for existing executor callers."""
        return self.decide(locale).selected_order

    def _configured_order(self, locale: str) -> tuple[str | None, list[str]]:
        for candidate in locale_routing_candidates(locale):
            if candidate in self.routing:
                return candidate, list(self.routing[candidate])
        return None, ["tavily"]

    def _apply_engine_health(self, fallback_order: list[str]) -> list[str]:
        """Move unhealthy configured engines later without dropping them."""
        if not self.engine_health or len(fallback_order) <= 1:
            return list(fallback_order)

        def rank(item: tuple[int, str]) -> tuple[int, int]:
            index, engine = item
            recommendation = str(self.engine_health.get(engine, {}).get("recommendation") or "healthy")
            return HEALTH_RECOMMENDATION_PRIORITY.get(recommendation, 0), index

        return [engine for _index, engine in sorted(enumerate(fallback_order), key=rank)]


def locale_routing_candidates(locale: str) -> list[str]:
    """Return BCP47-ish routing candidates from most to least specific."""
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

