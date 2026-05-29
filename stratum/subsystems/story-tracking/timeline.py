"""Cross-temporal timeline — scale registration, tracing, and rollup.

Operates on EventRecord.scale_refs via the EventRepository interface.
Pure functions — no network, no LLM, just data transformation.

Scale chain: daily → weekly → monthly → quarterly → yearly
"""

from datetime import date, timedelta
from typing import Optional

from story_contracts import EventRecord, ScaleRef, Prominence


# ── Constants ──

SCALE_ORDER = ["daily", "weekly", "monthly", "quarterly", "yearly"]

SCALE_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 91,
    "yearly": 365,
}


def _ref_scale(ref) -> str:
    """Extract scale from a ScaleRef that may be a dict or object."""
    return ref.scale if hasattr(ref, "scale") else ref.get("scale", "")


def scale_index(scale: str) -> int:
    """Return the ordinal position of a scale. -1 if invalid."""
    try:
        return SCALE_ORDER.index(scale)
    except ValueError:
        return -1


def next_scale(scale: str) -> Optional[str]:
    """Return the next broader scale, or None if at yearly."""
    idx = scale_index(scale)
    if idx < 0 or idx >= len(SCALE_ORDER) - 1:
        return None
    return SCALE_ORDER[idx + 1]


def prev_scale(scale: str) -> Optional[str]:
    """Return the next finer scale, or None if at daily."""
    idx = scale_index(scale)
    if idx <= 0:
        return None
    return SCALE_ORDER[idx - 1]


# ── Appearance Management ──

def record_appearance(
    event: EventRecord,
    scale: str,
    briefing_id: str,
    date_str: str,
    prominence: str = "supporting",
    synthesis: str = "",
    repo=None,
) -> EventRecord:
    """Record that an event appeared in a briefing at a given scale.

    Updates event.scale_refs and persists via repo if provided.

    Returns the updated event (already persisted if repo was given).
    """
    ref = ScaleRef(
        scale=scale,
        briefing_id=briefing_id,
        date=date_str,
        prominence=Prominence(prominence) if isinstance(prominence, str) else prominence,
        synthesis=synthesis,
    )
    event.scale_refs.append(ref)
    event.last_updated = date_str

    if repo:
        repo.update(event)

    return event


# ── Scale Chain Tracing ──

def trace_scales(event: EventRecord) -> dict:
    """Trace an event through all its scale appearances.

    Returns a dict with:
      - chain: ordered list of scales this event has appeared in
      - first_scale: the first (most granular) scale
      - highest_scale: the highest scale reached so far
      - missing: scales above highest_scale that haven't been reached
      - is_complete: True if appeared at all scales from first to yearly
    """
    appeared_scales = {_ref_scale(ref) for ref in event.scale_refs}
    ordered = sorted(appeared_scales, key=scale_index)

    first = ordered[0] if ordered else None
    highest = ordered[-1] if ordered else None

    # What scales are missing above the highest reached?
    missing = []
    if highest:
        highest_idx = scale_index(highest)
        for s in SCALE_ORDER[highest_idx + 1:]:
            missing.append(s)

    return {
        "event_id": event.id,
        "chain": ordered,
        "first_scale": first,
        "highest_scale": highest,
        "missing": missing,
        "is_complete": len(missing) == 0 and highest == "yearly",
    }


def trace_chain(event: EventRecord) -> list[dict]:
    """Return all scale_refs ordered by scale then date."""
    refs = sorted(
        event.scale_refs,
        key=lambda r: (scale_index(r.scale), r.date),
    )
    return [
        {"scale": r.scale, "briefing_id": r.briefing_id, "date": r.date,
         "prominence": r.prominence.value if isinstance(r.prominence, Prominence) else r.prominence,
         "synthesis": r.synthesis}
        for r in refs
    ]


# ── Rollup Discovery ──

def find_rollup_candidates(
    events: list[EventRecord],
    from_scale: str,
    to_scale: str,
) -> list[EventRecord]:
    """Find events that appeared at from_scale but not yet at to_scale.

    These are candidates for rollup into the next broader briefing.
    """
    to_idx = scale_index(to_scale)
    return [
        e for e in events
        if any(_ref_scale(ref) == from_scale for ref in e.scale_refs)
        and not any(scale_index(_ref_scale(ref)) >= to_idx for ref in e.scale_refs)
    ]


def events_for_scale_briefing(
    events: list[EventRecord],
    target_scale: str,
    since_days: Optional[int] = None,
) -> list[EventRecord]:
    """Get events that should be considered for a given scale's briefing.

    For daily: events from the last 1-2 days, including any unassigned.
    For weekly: events from last week that appeared in daily but not weekly yet.
    For monthly+: rollup candidates from the previous scale.

    If since_days is provided, filters by event.created within that window.
    """
    if target_scale == "daily":
        candidates = [
            e for e in events
            if e.status in ("emerging", "active")
        ]
    else:
        prev = prev_scale(target_scale)
        if prev:
            candidates = find_rollup_candidates(events, prev, target_scale)
        else:
            candidates = []

    if since_days:
        cutoff = (date.today() - timedelta(days=since_days)).isoformat()
        candidates = [e for e in candidates if e.created >= cutoff]

    # Sort by priority (ascending) then created (descending)
    candidates.sort(key=lambda e: (e.priority, e.created), reverse=False)
    candidates.sort(key=lambda e: e.priority)  # Stable: low number = high priority first

    return candidates


# ── Cross-Temporal Summary ──

def scale_summary(events: list[EventRecord]) -> dict:
    """Generate a multi-scale summary of all events."""
    result = {}
    for scale in SCALE_ORDER:
        count = sum(
            1 for e in events
            if any(_ref_scale(ref) == scale for ref in e.scale_refs)
        )
        result[scale] = {
            "total": count,
            "active": sum(
                1 for e in events
                if e.status in ("emerging", "active")
                and any(_ref_scale(ref) == scale for ref in e.scale_refs)
            ),
        }

    total_events = len(events)
    unassigned = sum(1 for e in events if len(e.scale_refs) == 0)
    fully_complete = sum(
        1 for e in events
        if trace_scales(e)["is_complete"]
    )

    return {
        "total_events": total_events,
        "unassigned": unassigned,
        "fully_complete": fully_complete,
        "scales": result,
    }


def timeline_gap_events(events: list[EventRecord], gap_days: int = 7) -> list[dict]:
    """Find events that haven't been updated in gap_days.

    Returns list of {event_id, title, last_updated, days_since, status}.
    """
    today = date.today()
    gaps = []
    for e in events:
        last = date.fromisoformat(e.last_updated[:10])
        delta = (today - last).days
        if delta >= gap_days and e.status not in ("resolved", "archived"):
            gaps.append({
                "event_id": e.id,
                "title": e.title,
                "last_updated": e.last_updated,
                "days_since": delta,
                "status": e.status,
            })
    gaps.sort(key=lambda g: g["days_since"], reverse=True)
    return gaps
