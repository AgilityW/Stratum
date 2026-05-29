"""Search curator — post-processing: dedup, score, prune.

Takes raw search results and produces a curated subset suitable for downstream
pipeline consumption. The curator is a pure function: results in → results out.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from stratum.subsystems.search.models import SearchResult


def _freshness_score(published_at: Optional[str], run_date: str) -> float:
    """Score based on recency. Today=1.0, yesterday=0.7, older=0.3."""
    if not published_at:
        return 0.7  # site-first: unknown date → assume recent (2026-05-30)
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
        name = t.get("name_en", "").lower()
        if name and name in text:
            hits += 1

    # Normalize: cap at 5 hits = 1.0
    return min(hits / 5.0, 1.0)


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
) -> list[SearchResult]:
    """Prune results by locale quota, source quota, and total cap."""
    # Already sorted by score from score()
    locale_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    kept: list[SearchResult] = []

    for r in results:
        if len(kept) >= total_cap:
            break

        loc = r.locale
        src = r.source_domain

        if locale_counts.get(loc, 0) >= max_per_locale:
            continue

        if source_counts.get(src, 0) >= max_per_source:
            continue

        locale_counts[loc] = locale_counts.get(loc, 0) + 1
        source_counts[src] = source_counts.get(src, 0) + 1
        kept.append(r)

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
) -> list[SearchResult]:
    """Full curation pipeline: extract domains → classify → score → prune."""
    # Extract domains and classify sources
    for r in results:
        r.with_domain()
        r.with_source_hint(classifications)

    # Score
    results = score(results, run_date, source_weights, entities, terms)

    # Prune
    results = prune(results, max_per_locale, max_per_source, total_cap)

    return results
