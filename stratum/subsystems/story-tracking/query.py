"""Story-tracking query engine — tag + time + scale multi-dimensional filtering.

All queries are pure functions operating on EventRecord lists.
No external dependencies — the repository provides the data, query filters it.

Query semantics:
  - topic_tags: AND matching (event must have ALL specified topics)
  - entity_tags: AND matching (event must have ALL specified entities)
  - date range: event.created in [date_from, date_to]
  - scale: event has at least one scale_ref with matching scale
"""

from datetime import date, timedelta
from typing import Optional

from story_contracts import EventRecord


# ── Core Query ──

def query_events(
    events: list[EventRecord],
    *,
    topics: Optional[list[str]] = None,
    entities: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    scale: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = "date_desc",
) -> list[EventRecord]:
    """Filter events by tag intersection, date range, scale, and status.

    All filters are AND-combined. Omit a filter to skip it.

    Args:
        events: Full list from repository
        topics: Event must have ALL of these topic_tags
        entities: Event must have ALL of these entity_tags
        date_from: ISO date lower bound (inclusive) on event.created
        date_to: ISO date upper bound (inclusive) on event.created
        scale: Event must have appeared at this briefing scale
        status: Match event.status
        sort_by: "date_desc" (newest first) or "date_asc" (oldest first)

    Returns filter + sorted list.
    """
    result = events

    if topics:
        topic_set = {t.lower() for t in topics}
        result = [
            e for e in result
            if topic_set <= {t.lower() for t in e.topic_tags}
        ]

    if entities:
        entity_set = {ent.lower() for ent in entities}
        result = [
            e for e in result
            if entity_set <= {ent.lower() for ent in e.entity_tags}
        ]

    if date_from:
        result = [e for e in result if e.created >= date_from]

    if date_to:
        result = [e for e in result if e.created <= date_to]

    if scale:
        result = [
            e for e in result
            if any(_ref_scale(ref) == scale for ref in e.scale_refs)
        ]

    if status:
        result = [e for e in result if e.status == status]

    # Sort
    reverse = sort_by == "date_desc"
    result.sort(key=lambda e: e.created, reverse=reverse)

    return result


# ── Convenience Queries ──

def recent_events(
    events: list[EventRecord],
    days: int = 7,
    **filters,
) -> list[EventRecord]:
    """Events from the last N days."""
    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=days)).isoformat()
    return query_events(events, date_from=from_date, date_to=to_date, **filters)


def events_by_topic(
    events: list[EventRecord],
    topic: str,
    **filters,
) -> list[EventRecord]:
    """Single-topic convenience query."""
    return query_events(events, topics=[topic], **filters)


def events_by_entity(
    events: list[EventRecord],
    entity: str,
    **filters,
) -> list[EventRecord]:
    """Single-entity convenience query."""
    return query_events(events, entities=[entity], **filters)


def active_events(events: list[EventRecord]) -> list[EventRecord]:
    """Events that are emerging or active."""
    return [
        e for e in events
        if e.status in ("emerging", "active")
    ]


def events_needing_attention(events: list[EventRecord]) -> list[EventRecord]:
    """Events that need attention: emerging/active, high priority, not in any briefing."""
    return [
        e for e in events
        if e.status in ("emerging", "active")
        and e.priority <= 3
        and len(e.scale_refs) == 0
    ]


# ── Cross-Temporal Queries ──

def events_by_scale(
    events: list[EventRecord],
    scale: str,
) -> list[EventRecord]:
    """All events that have appeared in briefings at a given scale."""
    return query_events(events, scale=scale)


def unassigned_events(events: list[EventRecord]) -> list[EventRecord]:
    """Events that have not appeared in ANY briefing yet."""
    return [e for e in events if len(e.scale_refs) == 0]


def events_missing_scale(
    events: list[EventRecord],
    scale: str,
) -> list[EventRecord]:
    """Events that have NOT yet appeared at the given scale."""
    return [
        e for e in events
        if not any(_ref_scale(ref) == scale for ref in e.scale_refs)
    ]


def _ref_scale(ref) -> str:
    """Extract scale from a ScaleRef that may be a dict or object."""
    return ref.scale if hasattr(ref, "scale") else ref.get("scale", "")

def query_stats(events: list[EventRecord]) -> dict:
    """Basic stats on the current event store."""
    total = len(events)
    by_status = {}
    by_scale = {"daily": 0, "weekly": 0, "monthly": 0, "quarterly": 0, "yearly": 0}
    all_topics = set()
    all_entities = set()

    for e in events:
        by_status[e.status] = by_status.get(e.status, 0) + 1
        for ref in e.scale_refs:
            s = _ref_scale(ref)
            if s in by_scale:
                by_scale[s] += 1
        all_topics.update(e.topic_tags)
        all_entities.update(e.entity_tags)

    return {
        "total": total,
        "by_status": by_status,
        "by_scale": by_scale,
        "unique_topics": len(all_topics),
        "unique_entities": len(all_entities),
    }
