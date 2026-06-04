"""Search curator — post-processing: dedup, score, prune.

Takes raw search results and produces a curated subset suitable for downstream
pipeline consumption. The curator is a pure function: results in → results out.
"""

from typing import Optional

from stratum.sourcing.discovery.models import SearchResult
from stratum.sourcing.discovery.curation_policy import SearchDiversityRanker, SearchResultScorer


def _freshness_score(published_at: Optional[str], run_date: str) -> float:
    """Compatibility wrapper for freshness scoring."""
    return SearchResultScorer().freshness_score(published_at, run_date)


def _entity_score(title: str, snippet: str, entities: list[dict], terms: list[dict]) -> float:
    """Compatibility wrapper for entity and term relevance scoring."""
    return SearchResultScorer().entity_score(title, snippet, entities, terms)


def _matched_entity_ids(result: SearchResult, entities: list[dict]) -> list[str]:
    """Compatibility wrapper for entity-dominance matching."""
    return SearchDiversityRanker().matched_entity_ids(result, entities)


def score(
    results: list[SearchResult],
    run_date: str,
    source_weights: dict[str, float],
    entities: list[dict],
    terms: list[dict],
) -> list[SearchResult]:
    """Score all results in-place. Returns the same list (mutated)."""
    return SearchResultScorer().score_results(results, run_date, source_weights, entities, terms)


def prune(
    results: list[SearchResult],
    max_per_locale: int = 30,
    max_per_source: int = 3,
    total_cap: int = 200,
    min_per_source_type: Optional[dict[str, int]] = None,
    entities: Optional[list[dict]] = None,
    max_per_entity: int = 0,
) -> list[SearchResult]:
    """Prune results by locale/source/entity quotas, source-type mix, and total cap."""
    return SearchDiversityRanker().rank(
        results,
        max_per_locale=max_per_locale,
        max_per_source=max_per_source,
        total_cap=total_cap,
        min_per_source_type=min_per_source_type,
        entities=entities,
        max_per_entity=max_per_entity,
    )


def curate(
    results: list[SearchResult],
    run_date: str,
    source_weights: dict[str, float],
    classifications: dict[str, list[str]],
    entities: list[dict],
    terms: list[dict],
    max_per_locale: int = 30,
    max_per_source: int = 3,
    total_cap: int = 200,
    min_per_source_type: Optional[dict[str, int]] = None,
    max_per_entity: int = 0,
) -> list[SearchResult]:
    """Full curation pipeline: extract domains → classify → score → prune."""
    # Extract domains and classify sources
    for r in results:
        r.with_domain()
        r.with_source_hint(classifications)

    # Score
    results = score(results, run_date, source_weights, entities, terms)

    # Prune
    results = prune(
        results,
        max_per_locale=max_per_locale,
        max_per_source=max_per_source,
        total_cap=total_cap,
        min_per_source_type=min_per_source_type,
        entities=entities,
        max_per_entity=max_per_entity,
    )

    return results
