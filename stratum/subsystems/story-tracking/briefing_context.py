"""Briefing context generator — produces a structured push-context for the agent.

Before generating a briefing at any scale (daily/weekly/monthly/...),
call generate_context() to get:
  - Events to carry forward from the last briefing
  - Judgments due for verification soon
  - Entities with coverage gaps
  - Active causal chains needing updates
  - New unassigned events

The agent injects this into its prompt to stay aware of ongoing stories.
"""

from datetime import date, timedelta
from typing import Optional

from story_contracts import EventRecord, CausalEdge, Judgment, BriefingContext


# ── Main Generator ──

def generate_context(
    domain_id: str,
    scale: str,
    target_date: str,
    events: list[EventRecord],
    edges: list[CausalEdge],
    judgments: list[Judgment],
    *,
    lookback_days: int = 7,
    coverage_gap_days: int = 14,
    due_within_days: int = 7,
) -> BriefingContext:
    """Generate the full briefing context for an agent.

    Args:
        domain_id: storage, robot, etc.
        scale: daily | weekly | monthly | quarterly | yearly
        target_date: the date the briefing covers
        events: all events from the repository
        edges: all causal edges from the repository
        judgments: all judgments from the repository
        lookback_days: how far back to look for carried-forward events
        coverage_gap_days: entities not mentioned for this many days count as gaps
        due_within_days: judgments due within this many days
    """
    # Carried-forward: events from last briefing at same or lower scale
    carried_forward = _carried_forward(events, scale, target_date, lookback_days)

    # Due judgments
    due_judgments = _due_judgments(judgments, target_date, due_within_days)

    # Coverage gaps
    coverage_gaps = _coverage_gaps(events, target_date, coverage_gap_days)

    # Active causal chains
    active_causal_chains = _active_chains(edges, events)

    # Unassigned events
    unassigned = _unassigned(events)

    return BriefingContext(
        scale=scale,
        date=target_date,
        domain_id=domain_id,
        carried_forward=carried_forward,
        due_judgments=due_judgments,
        coverage_gaps=coverage_gaps,
        active_causal_chains=active_causal_chains,
        unassigned_events=unassigned,
    )


# ── Private Helpers ──

def _carried_forward(
    events: list[EventRecord],
    scale: str,
    target_date: str,
    lookback_days: int,
) -> list[dict]:
    """Events that appeared in the previous briefing (same or lower scale)
    and are still active, sorted by priority.
    """
    SCALE_ORDER = ["daily", "weekly", "monthly", "quarterly", "yearly"]
    scale_idx = SCALE_ORDER.index(scale) if scale in SCALE_ORDER else 0

    cutoff = (date.fromisoformat(target_date) - timedelta(days=lookback_days)).isoformat()
    lower_scales = SCALE_ORDER[:scale_idx + 1]

    carried = []
    seen = set()

    for event in events:
        if event.status not in ("emerging", "active"):
            continue
        if event.id in seen:
            continue

        # Check if event appeared at a relevant scale within the lookback window
        for ref in event.scale_refs:
            ref_scale = ref.scale if hasattr(ref, "scale") else ref.get("scale", "")
            ref_date = ref.date if hasattr(ref, "date") else ref.get("date", "")
            if ref_scale in lower_scales and ref_date >= cutoff:
                carried.append({
                    "event_id": event.id,
                    "title": event.title,
                    "last_scale": ref_scale,
                    "last_date": ref_date,
                    "current_status": event.status,
                    "priority": event.priority,
                    "open_questions": event.open_questions[:3],
                })
                seen.add(event.id)
                break

    # Sort by priority (ascending = higher priority first), then by date
    carried.sort(key=lambda e: (e["priority"], e["last_date"]))
    return carried


def _due_judgments(
    judgments: list[Judgment],
    as_of: str,
    within_days: int,
) -> list[dict]:
    """Judgments that are overdue or due within within_days."""
    today = date.fromisoformat(as_of) if as_of else date.today()
    due = []

    for j in judgments:
        if j.verdict not in ("pending", "deferred"):
            continue
        try:
            expected = date.fromisoformat(j.expected_verification[:10])
        except (ValueError, TypeError):
            continue

        delta = (expected - today).days
        if delta <= within_days:
            due.append({
                "judgment_id": j.id,
                "hypothesis": j.hypothesis,
                "due_date": j.expected_verification,
                "days_remaining": delta,
                "verdict": j.verdict,
                "target_type": j.target_type,
                "target_ids": j.target_ids,
            })

    due.sort(key=lambda j: j["days_remaining"])
    return due


def _coverage_gaps(
    events: list[EventRecord],
    as_of: str,
    gap_days: int,
) -> list[dict]:
    """Entities that haven't appeared in any event for gap_days or more."""
    today = date.fromisoformat(as_of) if as_of else date.today()
    cutoff = (today - timedelta(days=gap_days)).isoformat()

    # Build entity → last_mentioned map
    entity_last = {}
    for event in events:
        for entity in event.entity_tags:
            if entity not in entity_last or event.last_updated > entity_last[entity]:
                entity_last[entity] = event.last_updated

    gaps = []
    for entity, last_date in entity_last.items():
        try:
            last = date.fromisoformat(last_date[:10])
        except (ValueError, TypeError):
            continue
        days_since = (today - last).days
        if days_since >= gap_days:
            gaps.append({
                "entity": entity,
                "last_mentioned": last_date,
                "days_since": days_since,
            })

    gaps.sort(key=lambda g: g["days_since"], reverse=True)
    return gaps


def _active_chains(
    edges: list[CausalEdge],
    events: list[EventRecord],
) -> list[dict]:
    """Causal chains that have one or more unverified edges."""
    event_status = {e.id: e.status for e in events}
    unverified = [e for e in edges if not e.verified]

    chains = {}
    for edge in unverified:
        chain_key = f"{edge.cause_id}-{edge.effect_id}"
        chains[chain_key] = {
            "cause_id": edge.cause_id,
            "effect_id": edge.effect_id,
            "mechanism": edge.mechanism[:200],
            "confidence": edge.confidence,
            "created": edge.created,
            "cause_status": event_status.get(edge.cause_id, "unknown"),
            "effect_status": event_status.get(edge.effect_id, "unknown"),
        }

    return list(chains.values())


def _unassigned(events: list[EventRecord]) -> list[str]:
    """Event IDs that have not appeared in any briefing yet."""
    return [e.id for e in events if len(e.scale_refs) == 0 and e.status in ("emerging", "active")]


# ── Context Formatter (for agent prompt injection) ──

def format_context_for_prompt(ctx: BriefingContext, max_items: int = 10) -> str:
    """Format BriefingContext as a structured text block for agent prompt injection.

    Limits each section to max_items to keep the prompt compact.
    """
    lines = []
    lines.append(f"## Briefing Context: {ctx.scale} briefing for {ctx.date}")
    lines.append("")

    # Carried forward
    if ctx.carried_forward:
        lines.append("### Events Carried Forward")
        for item in ctx.carried_forward[:max_items]:
            lines.append(f"- [{item['priority']}] **{item['title']}** ({item['event_id']})")
            lines.append(f"  Last: {item['last_scale']} on {item['last_date']}, status: {item['current_status']}")
            if item.get("open_questions"):
                lines.append(f"  Open: {'; '.join(item['open_questions'][:2])}")
        lines.append("")

    # Due judgments
    if ctx.due_judgments:
        lines.append("### Judgments Due")
        for item in ctx.due_judgments[:max_items]:
            urgency = "⚠️ OVERDUE" if item["days_remaining"] < 0 else f"in {item['days_remaining']}d"
            lines.append(f"- [{urgency}] {item['hypothesis'][:120]}")
        lines.append("")

    # Coverage gaps
    if ctx.coverage_gaps:
        lines.append("### Coverage Gaps")
        for item in ctx.coverage_gaps[:max_items]:
            lines.append(f"- **{item['entity']}**: last mentioned {item['days_since']} days ago")
        lines.append("")

    # Active causal chains
    if ctx.active_causal_chains:
        lines.append("### Active Causal Chains (Unverified)")
        for item in ctx.active_causal_chains[:max_items]:
            lines.append(f"- {item['cause_id']} → {item['effect_id']}: {item['mechanism'][:100]}")
        lines.append("")

    # Unassigned events
    if ctx.unassigned_events:
        lines.append(f"### Unassigned Events: {len(ctx.unassigned_events)}")
        lines.append("")

    return "\n".join(lines)
