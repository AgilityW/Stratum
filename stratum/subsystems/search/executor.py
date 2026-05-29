"""Search executor — concurrent query execution with rate limiting, retry, and fallback.

The executor is the bridge between queries and engines. It handles:
- Concurrent execution via ThreadPoolExecutor
- Per-engine rate limiting (token bucket)
- Retry with exponential backoff on transient failures
- Engine fallback: if primary engine fails, try secondary
"""

import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from stratum.subsystems.search.engine import RateLimitedError, SearchEngine
from stratum.subsystems.search.models import Query, QueryStats, SearchResult


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

    for engine_name in fallback_order:
        engine = engines.get(engine_name)
        if not engine:
            continue

        limiter = rate_limiters.get(engine_name)
        retries = max_retries.get(engine_name, 2)
        base_delay = backoff_base.get(engine_name, 1.0)

        for attempt in range(retries + 1):
            if limiter:
                if not limiter.wait_acquire(timeout=30.0):
                    continue  # try next engine

            try:
                results = engine.search(query.text, query.locale, query.id)
                latency = (time.monotonic() - t0) * 1000
                stats = QueryStats(
                    query_id=query.id,
                    engine_used=engine_name,
                    status="fallback" if attempt > 0 else "success",
                    results_count=len(results),
                    retries=attempt,
                    latency_ms=latency,
                )
                # Fill in default dates for engines that don't provide them
                for r in results:
                    if not r.published_at:
                        r.published_at = date
                return results, stats

            except RateLimitedError:
                if attempt < retries:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                # Rate limited after all retries — fall through to next engine
                break

            except Exception as e:
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
        status="failed",
        results_count=0,
        retries=0,
        latency_ms=latency,
        error="all engines exhausted",
    )
    return [], stats


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
            fallback_order = routing.get(q.locale, ["tavily"])
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
                    error=str(e),
                )

            all_stats.append(stats)

            for r in results:
                if r.url and r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)

    # Log summary
    succeeded = sum(1 for s in all_stats if s.status in ("success", "fallback"))
    failed = sum(1 for s in all_stats if s.status == "failed")
    print(f"Search: {succeeded}/{len(queries)} queries OK, {failed} failed, "
          f"{len(all_results)} unique results", file=sys.stderr)

    return all_results, all_stats
