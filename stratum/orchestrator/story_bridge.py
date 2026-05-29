"""Story Bridge — connects Agent-produced EventThreads to the Story-Tracking EventStore.

Thin adapter between the daily pipeline (Agent output) and the story-tracking subsystem.
Does not modify any existing files. Called by pipeline.py after Agent Edit stage.

Flow:
  Agent EventThread (dict) → convert → EventRecord → gate → EventStore
"""

import os
import sys
from typing import Optional

# Ensure story-tracking module is on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_STORY_TRACKING = os.path.join(_PROJECT_ROOT, "stratum", "subsystems", "story-tracking")
if _STORY_TRACKING not in sys.path:
    sys.path.insert(0, _STORY_TRACKING)

from story_contracts import EventRecord, TimelineEntry, ScaleRef, Prominence
from repository import JsonlEventRepository, StateManager
from gate import gate_event
from taxonomy import Taxonomy


# ── Main Bridge ──

def ingest_event_thread(
    thread: dict,
    domain_id: str,
    run_date: str,
    repo: JsonlEventRepository,
    state: StateManager,
    taxonomy: Taxonomy,
    *,
    briefing_id: str = "",
) -> Optional[EventRecord]:
    """Convert an Agent-produced EventThread dict to an EventRecord and persist it.

    Args:
        thread: Agent EventThread dict (from event-threads.json)
        domain_id: e.g. "storage"
        run_date: ISO date string
        repo: JsonlEventRepository for the domain
        state: StateManager for seq allocation
        taxonomy: Taxonomy for tag normalization
        briefing_id: e.g. "daily-2026-05-28" for scale_ref injection

    Returns the created EventRecord, or None if gate rejected it.
    """
    # ── 1. Convert ──
    event = _convert(thread, domain_id, state, taxonomy, run_date)

    # ── 2. Gate ──
    existing = repo.all()
    result = gate_event(event, existing)
    if not result.passed:
        print(f"[story-bridge] Gate rejected '{event.title}': {'; '.join(result.errors)}",
              file=sys.stderr)
        return None
    if result.warnings:
        for w in result.warnings:
            print(f"[story-bridge] Warning for '{event.title}': {w}", file=sys.stderr)

    # ── 3. Persist ──
    repo.add(event)

    # ── 4. Inject scale_ref ──
    if briefing_id:
        event.scale_refs.append(ScaleRef(
            scale="daily",
            briefing_id=briefing_id,
            date=run_date,
            prominence=Prominence.LEAD if thread.get("priority", 3) <= 2 else Prominence.SUPPORTING,
            synthesis=event.current_assessment[:300] if event.current_assessment else event.title,
        ))
        repo.update(event)

    return event


def ingest_batch(
    threads: list[dict],
    domain_id: str,
    run_date: str,
    repo: JsonlEventRepository,
    state: StateManager,
    taxonomy: Taxonomy,
    *,
    briefing_id: str = "",
) -> dict:
    """Ingest a batch of EventThreads. Returns stats dict."""
    stats = {"ingested": 0, "rejected": 0, "errors": []}
    for thread in threads:
        try:
            result = ingest_event_thread(
                thread, domain_id, run_date, repo, state, taxonomy,
                briefing_id=briefing_id,
            )
            if result:
                stats["ingested"] += 1
            else:
                stats["rejected"] += 1
        except Exception as e:
            stats["rejected"] += 1
            stats["errors"].append({"thread_id": thread.get("id", "?"), "error": str(e)})
    return stats


# ── Private: Conversion ──

def _convert(
    thread: dict,
    domain_id: str,
    state: StateManager,
    taxonomy: Taxonomy,
    run_date: str,
) -> EventRecord:
    """Convert Agent EventThread dict → EventRecord dataclass."""
    seq = state.next_event_seq()
    event_id = f"event-{domain_id}-{seq:04d}"

    # Extract tags from title + assessment
    all_text = f"{thread.get('title', '')} {thread.get('current_assessment', '')}"
    topic_tags = _extract_topics(all_text, taxonomy)
    entity_tags = _extract_entities(all_text, taxonomy)

    # Convert timeline
    timeline = []
    for entry in thread.get("timeline", []):
        timeline.append(TimelineEntry(
            date=entry.get("date", run_date),
            update_type="first_disclosure",
            summary=entry.get("event", entry.get("significance", ""))[:300],
            confidence="B",
            source_ids=[entry["source_cluster"]] if entry.get("source_cluster") else [],
        ))

    # Derive occurred_at from earliest timeline date
    occurred_at = None
    if timeline:
        occurred_at = min(t.date for t in timeline)

    return EventRecord(
        id=event_id,
        title=thread.get("title", "Untitled"),
        canonical_question=thread.get("canonical_question", ""),
        created=thread.get("created", run_date),
        last_updated=thread.get("last_updated", run_date),
        topic_tags=topic_tags,
        entity_tags=entity_tags,
        timeline=timeline,
        scale_refs=[],  # Will be added after gate passes
        source_ids=thread.get("parent_cluster_ids", []),
        occurred_at=occurred_at,
        first_reported_at=thread.get("created", run_date),
        status=thread.get("status", "emerging"),
        priority=thread.get("priority", 3),
        current_assessment=thread.get("current_assessment", ""),
        open_questions=thread.get("open_questions", []),
        watch_signals=thread.get("watch_signals", []),
    )


def _extract_topics(text: str, taxonomy: Taxonomy) -> list[str]:
    """Extract known topic tags from text via taxonomy keyword matching."""
    if not text:
        return []
    text_lower = text.lower()
    found = set()
    # Check all known topic aliases against the text
    for alias, tid in taxonomy._topics.items():
        if alias in text_lower:
            found.add(tid)
    return sorted(found)


def _extract_entities(text: str, taxonomy: Taxonomy) -> list[str]:
    """Extract known entity tags from text via taxonomy keyword matching."""
    if not text:
        return []
    text_lower = text.lower()
    found = set()
    for alias, eid in taxonomy._entities.items():
        if alias in text_lower:
            found.add(eid)
    return sorted(found)
