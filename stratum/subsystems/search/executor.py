"""Search executor — concurrent query execution with rate limiting, retry, and fallback.

The executor is the bridge between queries and engines. It handles:
- Concurrent execution via ThreadPoolExecutor
- Per-engine rate limiting (token bucket)
- Retry with exponential backoff on transient failures
- Engine fallback: if primary engine fails, try secondary
"""

import threading
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from stratum.subsystems.search.engine import RateLimitedError, SearchEngine
from stratum.subsystems.search.models import Query, QueryStats, SearchResult, canonicalize_url


def _locale_routing_candidates(locale: str) -> list[str]:
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


def _routing_for_locale(locale: str, routing: dict[str, list[str]]) -> list[str]:
    """Pick engine routing for exact or compatible locale variants."""
    for candidate in _locale_routing_candidates(locale):
        if candidate in routing:
            return routing[candidate]
    return ["tavily"]


class TokenBucket:
    """Simple token bucket rate limiter."""

    def __init__(self, rate: float):
        self.rate = rate  # tokens per second
        self.tokens = rate
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> bool:
        """Acquire one token. Returns True if acquired, False if would exceed rate."""
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

    def wait_acquire(self, timeout: float = 10.0) -> bool:
        """Block until a token is available or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(0.05)
        return False


def _search_with_retry(
    engines: dict[str, SearchEngine],
    fallback_order: list[str],
    query: Query,
    rate_limiters: dict[str, TokenBucket],
    max_retries: dict[str, int],
    backoff_base: dict[str, float],
    date: str,
) -> tuple[list[SearchResult], QueryStats]:
    """Execute a single query through engine chain with retry and fallback."""

    t0 = time.monotonic()
    last_error = ""
    saw_no_results = False

    for engine_index, engine_name in enumerate(fallback_order):
        engine = engines.get(engine_name)
        if not engine:
            last_error = f"{engine_name}: engine not configured"
            continue
        if query.include_domains and not getattr(engine, "supports_include_domains", True):
            last_error = f"{engine_name}: include_domains not supported"
            continue

        limiter = rate_limiters.get(engine_name)
        retries = max_retries.get(engine_name, 2)
        base_delay = backoff_base.get(engine_name, 1.0)

        for attempt in range(retries + 1):
            if limiter:
                if not limiter.wait_acquire(timeout=30.0):
                    last_error = f"{engine_name}: rate limiter timeout"
                    continue  # try next engine

            try:
                search_kwargs = {
                    "date": date,
                    "intent": query.intent,
                    "dimension": query.dimension,
                }
                if query.include_domains:
                    search_kwargs["include_domains"] = query.include_domains
                results = engine.search(
                    query.text,
                    query.locale,
                    query.id,
                    **search_kwargs,
                )
                if not results:
                    last_error = f"{engine_name}: no results"
                    saw_no_results = True
                    break
                unique_results = _dedupe_results(results)
                latency = (time.monotonic() - t0) * 1000
                stats = QueryStats(
                    query_id=query.id,
                    engine_used=engine_name,
                    status="fallback" if engine_index > 0 or attempt > 0 else "success",
                    results_count=len(unique_results),
                    locale=query.locale,
                    intent=query.intent,
                    dimension=query.dimension,
                    query_text=query.text,
                    include_domains=list(query.include_domains),
                    retries=attempt,
                    latency_ms=latency,
                )
                # Fill in default dates for engines that don't provide them
                for r in unique_results:
                    if not r.published_at:
                        r.published_at = date
                    r.query_dimension = query.dimension
                return unique_results, stats

            except RateLimitedError:
                last_error = f"{engine_name}: rate limited"
                if attempt < retries:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                # Rate limited after all retries — fall through to next engine
                break

            except Exception as e:
                last_error = f"{engine_name}: {type(e).__name__}: {e}"
                if attempt < retries:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                # Failed after all retries on this engine
                break

    # All engines failed
    latency = (time.monotonic() - t0) * 1000
    stats = QueryStats(
        query_id=query.id,
        engine_used=fallback_order[0] if fallback_order else "none",
        status="no_results" if saw_no_results and last_error.endswith("no results") else "failed",
        results_count=0,
        locale=query.locale,
        intent=query.intent,
        dimension=query.dimension,
        query_text=query.text,
        include_domains=list(query.include_domains),
        retries=0,
        latency_ms=latency,
        error=last_error or "all engines exhausted",
    )
    return [], stats


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    """Dedupe a single query's engine results by canonical URL."""
    unique: list[SearchResult] = []
    seen: set[str] = set()
    for result in results:
        canonical = result.canonical_url or canonicalize_url(result.url)
        if result.url and canonical not in seen:
            result.canonical_url = canonical
            seen.add(canonical)
            unique.append(result)
    return unique


def execute(
    queries: list[Query],
    engines: dict[str, SearchEngine],
    routing: dict[str, list[str]],
    max_rps: dict[str, float],
    max_retries: dict[str, int],
    backoff_base: dict[str, float],
    date: str,
    workers: int = 8,
) -> tuple[list[SearchResult], list[QueryStats]]:
    """Execute all queries concurrently, returning deduplicated results and statistics."""

    # Create rate limiters
    rate_limiters = {
        name: TokenBucket(rate) for name, rate in max_rps.items()
    }

    all_results: list[SearchResult] = []
    all_stats: list[QueryStats] = []
    seen_urls: set[str] = set()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for q in queries:
            q = q.with_substitutions(date)
            fallback_order = _routing_for_locale(q.locale, routing)
            futures[
                pool.submit(
                    _search_with_retry,
                    engines, fallback_order, q,
                    rate_limiters, max_retries, backoff_base, date,
                )
            ] = q

        for future in as_completed(futures):
            q = futures[future]
            try:
                results, stats = future.result()
            except Exception as e:
                stats = QueryStats(
                    query_id=q.id,
                    engine_used="unknown",
                    status="failed",
                    results_count=0,
                    locale=q.locale,
                    intent=q.intent,
                    dimension=q.dimension,
                    query_text=q.text,
                    include_domains=list(q.include_domains),
                    error=str(e),
                )

            all_stats.append(stats)

            for r in results:
                canonical = r.canonical_url or canonicalize_url(r.url)
                if r.url and canonical not in seen_urls:
                    r.canonical_url = canonical
                    seen_urls.add(canonical)
                    all_results.append(r)

    # Log summary
    succeeded = sum(1 for s in all_stats if s.status in ("success", "fallback"))
    failed = sum(1 for s in all_stats if s.status == "failed")
    no_results = sum(1 for s in all_stats if s.status == "no_results")
    print(f"Search: {succeeded}/{len(queries)} queries OK, {failed} failed, "
          f"{no_results} no-results, {len(all_results)} unique results", file=sys.stderr)

    return all_results, all_stats
