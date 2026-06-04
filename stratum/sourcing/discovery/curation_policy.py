"""Search result scoring and diversity ranking policies."""

from __future__ import annotations

import re
from datetime import datetime

from stratum.sourcing.discovery.models import SearchResult, canonicalize_url


class SearchResultScorer:
    """Score search results by source quality, freshness, and domain relevance."""

    def source_quality_score(self, result: SearchResult, source_weights: dict[str, float]) -> float:
        """Return normalized source quality from configured source-type weights."""
        return max(0.0, min(float(source_weights.get(result.source_type_hint, 0.5)), 1.0))

    def freshness_score(self, published_at: str | None, run_date: str) -> float:
        """Score based on recency. Today=1.0, yesterday=0.7, older=0.3."""
        if not published_at:
            return 0.3
        try:
            dt = datetime.fromisoformat(published_at[:10])
            run = datetime.strptime(run_date, "%Y-%m-%d")
            diff = (run.date() - dt.date()).days
            if diff <= 0:
                return 1.0
            if diff == 1:
                return 0.7
            return 0.3
        except Exception:
            return 0.3

    def entity_score(
        self,
        title: str,
        snippet: str,
        entities: list[dict],
        terms: list[dict],
    ) -> float:
        """Score based on configured entity and term mentions."""
        text = f"{title} {snippet}".lower()
        hits = 0

        for entity in entities:
            names = [entity.get("name_en", ""), entity.get("name_zh", "")]
            aliases = entity.get("aliases", [])
            if isinstance(aliases, str):
                aliases = []
            all_names = [name.lower() for name in names + aliases if name]
            if any(name in text for name in all_names):
                hits += 1

        for term in terms:
            aliases = term.get("aliases", [])
            if isinstance(aliases, str):
                aliases = []
            names = [term.get("id", ""), term.get("name_en", ""), term.get("name_zh", ""), *aliases]
            if any(name and name.lower() in text for name in names):
                hits += 1

        return min(hits / 5.0, 1.0)

    def novelty_score(
        self,
        result: SearchResult,
        title_counts: dict[str, int],
        source_counts: dict[str, int],
    ) -> float:
        """Score novelty within one raw result batch."""
        title_key = normalized_title_key(result.title)
        title_count = title_counts.get(title_key, 0) if title_key else 0
        source_count = source_counts.get(result.source_domain, 0)
        if title_count >= 3:
            return 0.2
        if title_count == 2:
            return 0.5
        if source_count >= 8:
            return 0.6
        return 1.0

    def score_results(
        self,
        results: list[SearchResult],
        run_date: str,
        source_weights: dict[str, float],
        entities: list[dict],
        terms: list[dict],
    ) -> list[SearchResult]:
        """Score all results in-place and return them in descending score order."""
        title_counts = batch_title_counts(results)
        source_counts = batch_source_counts(results)
        for result in results:
            source_quality = self.source_quality_score(result, source_weights)
            freshness = self.freshness_score(result.published_at, run_date)
            relevance = self.entity_score(result.title, result.snippet, entities, terms)
            novelty = self.novelty_score(result, title_counts, source_counts)
            result.score = round(
                source_quality * 0.3
                + freshness * 0.25
                + relevance * 0.3
                + novelty * 0.15,
                3,
            )

        results.sort(key=lambda result: result.score, reverse=True)
        return results


def normalized_title_key(title: str) -> str:
    """Normalize a title for novelty scoring without changing result identity."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def batch_title_counts(results: list[SearchResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        key = normalized_title_key(result.title)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def batch_source_counts(results: list[SearchResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        source = result.source_domain or ""
        if not source:
            continue
        counts[source] = counts.get(source, 0) + 1
    return counts


class SearchDiversityRanker:
    """Keep high-scoring results while enforcing source, locale, and entity diversity."""

    def matched_entity_ids(self, result: SearchResult, entities: list[dict]) -> list[str]:
        """Return configured entity ids mentioned in the result title/snippet."""
        text = f"{result.title} {result.snippet}".lower()
        matches: list[str] = []

        for entity in entities:
            entity_id = entity.get("id", "")
            aliases = entity.get("aliases", [])
            if isinstance(aliases, str):
                aliases = []
            names = [
                entity_id,
                entity.get("name_en", ""),
                entity.get("name_zh", ""),
                *aliases,
            ]
            if any(name and name.lower() in text for name in names):
                matches.append(entity_id)

        return matches

    def rank(
        self,
        results: list[SearchResult],
        max_per_locale: int = 30,
        max_per_source: int = 3,
        total_cap: int = 200,
        min_per_source_type: dict[str, int] | None = None,
        entities: list[dict] | None = None,
        max_per_entity: int = 0,
    ) -> list[SearchResult]:
        """Prune results by locale/source/entity quotas, source-type mix, and total cap."""
        locale_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        entity_counts: dict[str, int] = {}
        seen_urls: set[str] = set()
        kept: list[SearchResult] = []

        def can_keep(result: SearchResult, enforce_entity_cap: bool = True) -> bool:
            if len(kept) >= total_cap:
                return False

            locale = result.locale
            source = result.source_domain

            if locale_counts.get(locale, 0) >= max_per_locale:
                return False

            if source_counts.get(source, 0) >= max_per_source:
                return False

            canonical = result.canonical_url or canonicalize_url(result.url)
            if canonical in seen_urls:
                return False

            if enforce_entity_cap and max_per_entity > 0 and entities:
                matched_entities = self.matched_entity_ids(result, entities)
                if matched_entities and any(
                    entity_counts.get(entity_id, 0) >= max_per_entity
                    for entity_id in matched_entities
                ):
                    return False

            return True

        def keep(result: SearchResult) -> None:
            locale = result.locale
            source = result.source_domain
            source_type = result.source_type_hint or "unknown"

            locale_counts[locale] = locale_counts.get(locale, 0) + 1
            source_counts[source] = source_counts.get(source, 0) + 1
            type_counts[source_type] = type_counts.get(source_type, 0) + 1
            for entity_id in self.matched_entity_ids(result, entities or []):
                entity_counts[entity_id] = entity_counts.get(entity_id, 0) + 1
            result.canonical_url = result.canonical_url or canonicalize_url(result.url)
            seen_urls.add(result.canonical_url)
            kept.append(result)

        for source_type, minimum in (min_per_source_type or {}).items():
            if minimum <= 0:
                continue
            for result in results:
                if type_counts.get(source_type, 0) >= minimum:
                    break
                if result.source_type_hint != source_type:
                    continue
                if can_keep(result, enforce_entity_cap=False):
                    keep(result)

        for result in results:
            if len(kept) >= total_cap:
                break
            if can_keep(result):
                keep(result)

        return kept
