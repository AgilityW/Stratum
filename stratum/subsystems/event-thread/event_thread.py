"""Event Thread Engine — Cross-day story tracking.

Deterministic core: data model, lifecycle state machine, thread matching (Jaccard),
archiving, watch query generation.

LLM-driven semantic matching is documented in skills/event-thread-engine/SKILL.md.
The deterministic fallback here uses entity-overlap matching (same algorithm as cluster stage).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


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


def compute_thread_status(thread: EventThread, run_date_str: str) -> str:
    """Determine thread status based on time since last update."""
    run_date = date.fromisoformat(run_date_str)

    if not thread.timeline:
        return thread.status

    first_date = date.fromisoformat(thread.timeline[0].date)
    last_date = date.fromisoformat(thread.timeline[-1].date)

    days_since_last = (run_date - last_date).days

    if days_since_last >= 30:
        return "resolved"
    elif days_since_last >= 7:
        return "cooling"
    elif thread.status == "emerging" and days_since_last == 0:
        return "emerging"
    else:
        return "active"


def should_archive(thread: EventThread, run_date_str: str) -> bool:
    """Archive resolved threads after 7 days of inactivity."""
    if thread.status != "resolved":
        return False
    run_date = date.fromisoformat(run_date_str)
    last_date = date.fromisoformat(thread.last_updated)
    return (run_date - last_date).days > 7


def jaccard_similarity(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


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
    cluster_set = {s.lower() for s in (cluster_entities | cluster_terms)}
    if not cluster_set:
        return None

    best_id = None
    best_score = 0.0

    for tid, thread in threads.items():
        # Use watch_signals + canonical_question as proxy for thread signature
        thread_set = {s.lower() for s in
                      (set(thread.watch_signals) | set(thread.canonical_question.lower().split()))}
        score = jaccard_similarity(cluster_set, thread_set)
        if score > best_score:
            best_score = score
            best_id = tid

    return best_id if best_score >= threshold else None


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
    thread.confidence_history.append({"date": run_date, "confidence": confidence})


def generate_watch_queries(
    threads: dict[str, EventThread],
    max_queries: int = MAX_WATCH_QUERIES_PER_DAY,
) -> list[dict]:
    """Generate watch queries from active/emerging threads for next day's collection."""
    queries = []
    for tid, thread in threads.items():
        if thread.status not in ("active", "emerging"):
            continue
        for signal in thread.watch_signals:
            queries.append({
                "query": signal,
                "locale": "en",
                "source": f"thread:{tid}",
                "reason": f"watch signal from {thread.title}",
            })
            if len(queries) >= max_queries:
                return queries
    return queries


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
) -> dict:
    """Process new clusters against existing threads.

    Returns: {threads, stats, watch_queries}
    """
    stats = {"matched": 0, "created": 0, "skipped": 0, "archived": 0}
    new_clusters = new_clusters or []

    # Archive resolved threads
    before_count = len(threads)
    threads = archive_resolved(threads, run_date)
    stats["archived"] = before_count - len([t for t in threads.values() if t.status != "archived"])

    seq = len(threads) + 1

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
            if (len(entities) + len(terms)) >= 2 and seq - len(threads) <= MAX_THREADS:
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

    watch_queries = generate_watch_queries(threads)

    return {
        "threads": threads,
        "stats": stats,
        "watch_queries": watch_queries,
    }
