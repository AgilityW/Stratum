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

from typing import Optional

from stratum.subsystems.story_tracking.context_policy import ContextSelectionPolicy
from stratum.subsystems.story_tracking.story_contracts import (
    BriefingContext,
    CausalEdge,
    EventRecord,
    Judgment,
)


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
    coverage_entities: Optional[list[str]] = None,
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
        coverage_entities: optional domain coverage universe; entities that
            have never appeared are reported as gaps too
    """
    policy = ContextSelectionPolicy()
    carried_forward = policy.carried_forward(events, scale, target_date, lookback_days)
    due_judgments = policy.due_judgments(judgments, target_date, due_within_days)
    coverage_gaps = policy.coverage_gaps(
        events,
        target_date,
        coverage_gap_days,
        coverage_entities=coverage_entities,
    )
    active_causal_chains = policy.active_chains(edges, events, target_date)
    unassigned = policy.unassigned(events, target_date)

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
    return ContextSelectionPolicy().carried_forward(events, scale, target_date, lookback_days)


def _due_judgments(
    judgments: list[Judgment],
    as_of: str,
    within_days: int,
) -> list[dict]:
    """Judgments that are overdue or due within within_days."""
    return ContextSelectionPolicy().due_judgments(judgments, as_of, within_days)


def _coverage_gaps(
    events: list[EventRecord],
    as_of: str,
    gap_days: int,
    coverage_entities: Optional[list[str]] = None,
) -> list[dict]:
    """Entities that haven't appeared in any event for gap_days or more."""
    return ContextSelectionPolicy().coverage_gaps(events, as_of, gap_days, coverage_entities)


def _active_chains(
    edges: list[CausalEdge],
    events: list[EventRecord],
    as_of: Optional[str] = None,
) -> list[dict]:
    """Causal chains that have one or more unverified edges."""
    return ContextSelectionPolicy().active_chains(edges, events, as_of)


def _unassigned(events: list[EventRecord], as_of: Optional[str] = None) -> list[str]:
    """Event IDs that have not appeared in any briefing yet."""
    return ContextSelectionPolicy().unassigned(events, as_of)


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
            if item.get("last_mentioned"):
                lines.append(f"- **{item['entity']}**: last mentioned {item['days_since']} days ago")
            else:
                lines.append(f"- **{item['entity']}**: no prior coverage found")
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
        for event_id in ctx.unassigned_events[:max_items]:
            lines.append(f"- {event_id}")
        lines.append("")

    return "\n".join(lines)
