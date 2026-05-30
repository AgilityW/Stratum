"""Search curator — post-processing: dedup, score, prune.

Takes raw search results and produces a curated subset suitable for downstream
pipeline consumption. The curator is a pure function: results in → results out.
"""

from datetime import datetime
from typing import Optional

from stratum.subsystems.search.models import SearchResult, canonicalize_url


def _freshness_score(published_at: Optional[str], run_date: str) -> float:
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


def _entity_score(title: str, snippet: str, entities: list[dict], terms: list[dict]) -> float:
    """Score based on entity and term mentions. 0-1, normalized."""
    text = f"{title} {snippet}".lower()
    hits = 0

    for e in entities:
        names = [e.get("name_en", ""), e.get("name_zh", "")]
        aliases = e.get("aliases", [])
        if isinstance(aliases, str):
            aliases = []
        all_names = [n.lower() for n in names + aliases if n]
        if any(name in text for name in all_names):
            hits += 1

    for t in terms:
        aliases = t.get("aliases", [])
        if isinstance(aliases, str):
            aliases = []
        names = [t.get("id", ""), t.get("name_en", ""), t.get("name_zh", ""), *aliases]
        if any(name and name.lower() in text for name in names):
            hits += 1

    # Normalize: cap at 5 hits = 1.0
    return min(hits / 5.0, 1.0)


def _matched_entity_ids(result: SearchResult, entities: list[dict]) -> list[str]:
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


def score(
    results: list[SearchResult],
    run_date: str,
    source_weights: dict[str, float],
    entities: list[dict],
    terms: list[dict],
) -> list[SearchResult]:
    """Score all results in-place. Returns the same list (mutated)."""
    for r in results:
        sw = source_weights.get(r.source_type_hint, 0.5)
        fs = _freshness_score(r.published_at, run_date)
        es = _entity_score(r.title, r.snippet, entities, terms)
        r.score = round(sw * 0.4 + fs * 0.3 + es * 0.3, 3)

    # Sort descending by score
    results.sort(key=lambda r: r.score, reverse=True)
    return results


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
    # Already sorted by score from score()
    locale_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    entity_counts: dict[str, int] = {}
    seen_urls: set[str] = set()
    kept: list[SearchResult] = []

    def can_keep(r: SearchResult, enforce_entity_cap: bool = True) -> bool:
        if len(kept) >= total_cap:
            return False

        loc = r.locale
        src = r.source_domain

        if locale_counts.get(loc, 0) >= max_per_locale:
            return False

        if source_counts.get(src, 0) >= max_per_source:
            return False

        canonical = r.canonical_url or canonicalize_url(r.url)
        if canonical in seen_urls:
            return False

        if enforce_entity_cap and max_per_entity > 0 and entities:
            matched_entities = _matched_entity_ids(r, entities)
            if matched_entities and any(entity_counts.get(eid, 0) >= max_per_entity for eid in matched_entities):
                return False

        return True

    def keep(r: SearchResult) -> None:
        loc = r.locale
        src = r.source_domain
        source_type = r.source_type_hint or "unknown"

        locale_counts[loc] = locale_counts.get(loc, 0) + 1
        source_counts[src] = source_counts.get(src, 0) + 1
        type_counts[source_type] = type_counts.get(source_type, 0) + 1
        for entity_id in _matched_entity_ids(r, entities or []):
            entity_counts[entity_id] = entity_counts.get(entity_id, 0) + 1
        r.canonical_url = r.canonical_url or canonicalize_url(r.url)
        seen_urls.add(r.canonical_url)
        kept.append(r)

    # First reserve a configurable minimum mix of source types. This prevents
    # high-volume media results from crowding out available official/analyst
    # evidence while still respecting locale/source/total caps.
    for source_type, minimum in (min_per_source_type or {}).items():
        if minimum <= 0:
            continue
        for r in results:
            if type_counts.get(source_type, 0) >= minimum:
                break
            if r.source_type_hint != source_type:
                continue
            if can_keep(r, enforce_entity_cap=False):
                keep(r)

    for r in results:
        if len(kept) >= total_cap:
            break
        if can_keep(r):
            keep(r)

    return kept


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
