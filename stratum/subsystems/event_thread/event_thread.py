"""Event Thread Engine — Cross-day story tracking.

Deterministic core: data model, lifecycle state machine, thread matching (Jaccard),
archiving, watch query generation.

LLM-driven semantic matching is documented in skills/event-thread-engine/SKILL.md.
The deterministic fallback here uses entity-overlap matching (same algorithm as cluster stage).
"""

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Optional

from stratum.subsystems.event_thread.lifecycle_policy import ThreadLifecycleScorer


@dataclass
class TimelineEntry:
    date: str                          # ISO date
    cluster_id: str
    update_type: str                   # first_disclosure | confirmation | contradiction | quantification | rehash
    summary: str
    confidence_after: str


@dataclass
class EventThread:
    id: str
    title: str
    canonical_question: str
    status: str                        # emerging | active | cooling | resolved | archived
    priority: str                      # high | medium | low
    created: str                       # ISO date
    last_updated: str
    timeline: list[TimelineEntry] = field(default_factory=list)
    confidence: str = "C"
    confidence_history: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    watch_signals: list[str] = field(default_factory=list)
    close_conditions: list[str] = field(default_factory=list)
    briefing_refs: list[dict] = field(default_factory=list)
    # briefing_refs format: {"briefing_id": str, "scale": str, "date": str,
    #                        "section": str, "prominence": str}


# ── Lifecycle State Machine ──

LIFECYCLE_RULES = {
    "emerging": {"inactive_days": 0,   "next": None},       # Just created
    "active":   {"inactive_days": 0,   "next": "cooling"},   # Recent update
    "cooling":  {"inactive_days": 7,   "next": "resolved"},  # No update ≥7 days
    "resolved": {"inactive_days": 30,  "next": "archived"},  # No update ≥30 days
    "archived": {"inactive_days": 37,  "next": None},        # Resolved ≥7 days
}

MAX_THREADS = 30
MIN_THREADS = 5
MAX_WATCH_QUERIES_PER_DAY = 10
WATCH_QUERY_STATUSES = {"emerging", "active", "cooling"}
MATCHABLE_STATUSES = {"emerging", "active", "cooling"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_DEFAULT_LIFECYCLE_SCORER = ThreadLifecycleScorer()


def _next_thread_sequence(domain_id: str, threads: dict[str, EventThread]) -> int:
    """Return the next numeric suffix for a domain without colliding with existing IDs."""
    prefix = f"et-{domain_id}-"
    max_seq = 0
    for thread_id in threads:
        if not thread_id.startswith(prefix):
            continue
        suffix = thread_id[len(prefix):]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return max_seq + 1


def compute_thread_status(thread: EventThread, run_date_str: str) -> str:
    """Determine thread status based on time since last update."""
    return evaluate_thread_lifecycle(thread, run_date_str)["status"]


def evaluate_thread_lifecycle(thread: EventThread, run_date_str: str) -> dict:
    """Return structured lifecycle diagnostics for one event thread."""
    run_date = date.fromisoformat(run_date_str)
    decision = _DEFAULT_LIFECYCLE_SCORER.evaluate(
        current_status=thread.status,
        run_date=run_date_str,
        observed_dates=_timeline_dates_through(thread, run_date),
        last_updated=thread.last_updated,
    )
    return {
        "thread_id": thread.id,
        "status": decision.status,
        "previous_status": thread.status,
        "momentum": decision.momentum,
        "lifecycle_score": decision.lifecycle_score,
        "days_since_last": decision.days_since_last,
        "observed_updates": decision.observed_updates,
        "should_archive": decision.should_archive,
        "reason": decision.reason,
    }


def lifecycle_diagnostics(threads: dict[str, EventThread], run_date_str: str) -> list[dict]:
    """Return lifecycle diagnostics ordered for downstream review."""
    diagnostics = [evaluate_thread_lifecycle(thread, run_date_str) for thread in threads.values()]
    return sorted(
        diagnostics,
        key=lambda item: (
            str(item.get("thread_id") or ""),
        ),
    )


def _timeline_dates_through(thread: EventThread, run_date: date) -> list[date]:
    """Return sorted timeline dates visible at run_date."""
    dates: list[date] = []
    for entry in thread.timeline:
        try:
            entry_date = date.fromisoformat(str(entry.date)[:10])
        except (ValueError, TypeError):
            continue
        if entry_date <= run_date:
            dates.append(entry_date)
    return sorted(dates)


def should_archive(thread: EventThread, run_date_str: str) -> bool:
    """Archive resolved threads after 7 days of inactivity."""
    run_date = date.fromisoformat(run_date_str)
    decision = _DEFAULT_LIFECYCLE_SCORER.evaluate(
        current_status=thread.status,
        run_date=run_date_str,
        observed_dates=_timeline_dates_through(thread, run_date),
        last_updated=thread.last_updated,
    )
    return decision.should_archive


def jaccard_similarity(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _signature_terms(values) -> set[str]:
    """Normalize signal phrases into comparable lowercase tokens."""
    terms = set()
    for value in values:
        text = str(value or "").lower()
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text):
            if len(token) >= 2:
                terms.add(token)
        if text.strip():
            terms.add(text.strip())
    return terms


def match_cluster_to_thread(
    cluster_entities: set[str],
    cluster_terms: set[str],
    threads: dict[str, EventThread],
    threshold: float = 0.25,
) -> Optional[str]:
    """Deterministic matching: find the best thread by entity/term overlap.

    Returns thread_id if Jaccard similarity > threshold, else None.
    For high-quality semantic matching, use the LLM path in SKILL.md.
    """
    cluster_set = _signature_terms(cluster_entities | cluster_terms)
    if not cluster_set:
        return None

    best_id = None
    best_score = 0.0

    for tid, thread in threads.items():
        if thread.status not in MATCHABLE_STATUSES:
            continue
        # Use all stable thread descriptors as a proxy for semantic signature.
        # Some threads are created before the LLM supplies watch_signals, so the
        # title and timeline summaries are necessary fallback anchors.
        thread_set = _thread_signature(thread)
        score = jaccard_similarity(cluster_set, thread_set)
        if score > best_score:
            best_score = score
            best_id = tid

    return best_id if best_score >= threshold else None


def _thread_signature(thread: EventThread) -> set[str]:
    """Return tokenized descriptors that can match future clusters."""
    values = set(thread.watch_signals)
    values.add(thread.title)
    values.add(thread.canonical_question)
    values.update(thread.open_questions)
    values.update(thread.close_conditions)
    values.update(entry.summary for entry in thread.timeline)
    return _signature_terms(values)


def create_thread(
    domain_id: str,
    seq: int,
    title: str,
    canonical_question: str,
    priority: str,
    run_date: str,
    cluster_id: str,
    summary: str,
    confidence: str,
    watch_signals: list[str],
    close_conditions: list[str],
) -> EventThread:
    """Create a new EventThread from a first-disclosure cluster."""
    tid = f"et-{domain_id}-{seq:04d}"
    return EventThread(
        id=tid,
        title=title,
        canonical_question=canonical_question,
        status="emerging",
        priority=priority,
        created=run_date,
        last_updated=run_date,
        timeline=[TimelineEntry(
            date=run_date,
            cluster_id=cluster_id,
            update_type="first_disclosure",
            summary=summary[:300],
            confidence_after=confidence,
        )],
        confidence=confidence,
        confidence_history=[{"date": run_date, "confidence": confidence}],
        watch_signals=watch_signals,
        close_conditions=close_conditions,
    )


def add_update(
    thread: EventThread,
    run_date: str,
    cluster_id: str,
    update_type: str,
    summary: str,
    confidence: str,
):
    """Add a new timeline entry to an existing thread."""
    thread.timeline.append(TimelineEntry(
        date=run_date,
        cluster_id=cluster_id,
        update_type=update_type,
        summary=summary,
        confidence_after=confidence,
    ))
    thread.last_updated = run_date
    thread.status = compute_thread_status(thread, run_date)
    thread.confidence = confidence
    thread.confidence_history.append({"date": run_date, "confidence": confidence})


def generate_watch_queries(
    threads: dict[str, EventThread],
    max_queries: int = MAX_WATCH_QUERIES_PER_DAY,
    locales: Optional[list[str]] = None,
) -> list[dict]:
    """Generate watch queries from active/emerging threads for next day's collection."""
    queries = []
    seen = set()
    locales = locales or ["en"]
    ordered_threads = sorted(
        threads.items(),
        key=lambda item: (
            PRIORITY_ORDER.get(item[1].priority, 9),
            -_thread_lifecycle_rank(item[1]),
            _date_sort_key(item[1].last_updated),
        ),
    )
    for tid, thread in ordered_threads:
        if thread.status not in WATCH_QUERY_STATUSES:
            continue
        for signal in _watch_query_signals(thread):
            query = str(signal or "").strip()
            if not query:
                continue
            for locale in locales:
                dedupe_key = (query.lower(), locale)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                queries.append({
                    "query": query,
                    "locale": locale,
                    "source": f"thread:{tid}",
                    "reason": f"watch signal from {thread.title}",
                })
                if len(queries) >= max_queries:
                    return queries
    return queries


def _date_sort_key(value: str) -> int:
    """Return an inverted ISO-date sort key so recent threads win within priority."""
    date_text = str(value or "")[:10]
    if not date_text:
        return 9999999
    try:
        ordinal = date.fromisoformat(date_text).toordinal()
    except ValueError:
        return 9999999
    return -ordinal


def _thread_lifecycle_rank(thread: EventThread) -> float:
    """Return lifecycle score for ranking watch-query candidates."""
    return _DEFAULT_LIFECYCLE_SCORER.score_status(
        status=thread.status,
        observed_count=len(thread.timeline),
    )


def _watch_query_signals(thread: EventThread) -> list[str]:
    """Return explicit watch signals, or a conservative thread-title fallback."""
    explicit = [str(signal).strip() for signal in thread.watch_signals if str(signal or "").strip()]
    if explicit:
        return explicit
    fallback = str(thread.canonical_question or thread.title or "").strip()
    return [fallback] if fallback else []


def archive_resolved(
    threads: dict[str, EventThread],
    run_date: str,
) -> dict[str, EventThread]:
    """Move resolved threads to archived after 7 days."""
    for tid in list(threads.keys()):
        if should_archive(threads[tid], run_date):
            threads[tid].status = "archived"
    return threads


def evolve_threads(
    threads: dict[str, EventThread],
    domain_id: str,
    run_date: str,
    # New clusters to process (from agent — see SKILL.md for LLM matching)
    new_clusters: list[dict] = None,
    watch_locales: Optional[list[str]] = None,
) -> dict:
    """Process new clusters against existing threads.

    Returns: {threads, stats, watch_queries, lifecycle_diagnostics}
    """
    stats = {"matched": 0, "created": 0, "skipped": 0, "archived": 0}
    new_clusters = new_clusters or []

    # Archive resolved threads
    before_archived = sum(1 for t in threads.values() if t.status == "archived")
    threads = archive_resolved(threads, run_date)
    after_archived = sum(1 for t in threads.values() if t.status == "archived")
    stats["archived"] = max(0, after_archived - before_archived)

    seq = _next_thread_sequence(domain_id, threads)

    for cluster in new_clusters:
        entities = set(cluster.get("entities", []))
        terms = set(cluster.get("terms", []))

        matched_id = match_cluster_to_thread(entities, terms, threads)
        if matched_id:
            add_update(
                threads[matched_id],
                run_date,
                cluster.get("id", ""),
                cluster.get("update_type", "confirmation"),
                cluster.get("canonical_summary", ""),
                cluster.get("confidence", "C"),
            )
            stats["matched"] += 1
        else:
            # Auto-create only if it looks substantial
            if (len(entities) + len(terms)) >= 2 and len(threads) < MAX_THREADS:
                new_thread = create_thread(
                    domain_id, seq,
                    title=cluster.get("canonical_title", "Untitled"),
                    canonical_question=cluster.get("canonical_question", ""),
                    priority=cluster.get("priority", "medium"),
                    run_date=run_date,
                    cluster_id=cluster.get("id", ""),
                    summary=cluster.get("canonical_summary", ""),
                    confidence=cluster.get("confidence", "C"),
                    watch_signals=cluster.get("watch_signals", []),
                    close_conditions=cluster.get("close_conditions", []),
                )
                threads[new_thread.id] = new_thread
                stats["created"] += 1
                seq += 1
            else:
                stats["skipped"] += 1

    watch_queries = generate_watch_queries(threads, locales=watch_locales)

    return {
        "threads": threads,
        "stats": stats,
        "watch_queries": watch_queries,
        "lifecycle_diagnostics": lifecycle_diagnostics(threads, run_date),
    }
