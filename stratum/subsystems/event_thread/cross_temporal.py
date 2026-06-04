"""Cross-Temporal Engine — vertical event linkage across time scales.

Deterministic core: register appearances, roll up across scales, trace thread chains.
LLM-driven narrative synthesis documented in skills/event-thread-engine/SKILL.md.
"""

from datetime import date
from typing import Optional

from stratum.contracts import (
    BriefingRef, CrossTemporalLink, CrossTemporalState, RegisterInput,
    RollupInput, TraceResult, SCALE_ORDER, VALID_SCALES,
    scale_higher, scale_lower,
)


# ── Register Appearances ──

def register_appearance(state: CrossTemporalState, input: RegisterInput) -> CrossTemporalLink:
    """Record that a thread appeared in a briefing at a specific scale.

    Creates a new CrossTemporalLink if this is the thread's first appearance.
    Otherwise appends to the existing link.

    Returns the updated link.
    """
    link = state.get_or_create_link(input.thread_id, created_scale=input.scale)
    ref = BriefingRef(
        briefing_id=input.briefing_id,
        scale=input.scale,
        date=input.date,
        section=input.section,
        prominence=input.prominence,
        synthesis=input.synthesis,
    )
    link.add_appearance(ref)
    return link


def register_batch(state: CrossTemporalState, inputs: list[RegisterInput]) -> list[CrossTemporalLink]:
    """Register multiple appearances in one batch."""
    links = []
    for inp in inputs:
        links.append(register_appearance(state, inp))
    return links


# ── Rollup ──

def rollup(state: CrossTemporalState, input: RollupInput) -> dict:
    """Roll up lower-scale threads into a higher-scale thread.

    Links source threads to the target thread via merged_into/child_threads.
    Registers the target thread's appearance at the higher scale.

    Returns stats dict and modified links.
    """
    stats = {"rolled_up": 0, "already_merged": 0, "not_found": 0}
    modified = []

    target_link = state.get_or_create_link(input.target_thread_id, created_scale=input.target_scale)

    # Register target's own appearance
    target_ref = BriefingRef(
        briefing_id=input.briefing_id,
        scale=input.target_scale,
        date=input.date,
        section="rollup",
        prominence="lead",
        synthesis=input.synthesis,
    )
    target_link.add_appearance(target_ref)

    for src_id in input.source_thread_ids:
        src_link = state.links.get(src_id)
        if src_link is None:
            stats["not_found"] += 1
            continue

        if src_link.merged_into is not None:
            stats["already_merged"] += 1
            continue

        src_link.merged_into = input.target_thread_id
        target_link.child_threads.append(src_id)
        stats["rolled_up"] += 1
        modified.append(src_link)

    modified.append(target_link)
    return {"stats": stats, "links": modified}


# ── Trace ──

def trace_thread(state: CrossTemporalState, thread_id: str) -> Optional[TraceResult]:
    """Trace a thread vertically across all time scales.

    Follows the chain: this thread → merged_into → merged_into → ...
    Returns the full path and identifies missing scales.
    """
    link = state.links.get(thread_id)
    if link is None:
        return None

    # Collect all appearances in the chain
    chain = list(link.appearances)

    # Follow merged_into chain upward
    current_id = link.merged_into
    highest_id = None
    while current_id:
        parent = state.links.get(current_id)
        if parent is None:
            break
        chain.extend(parent.appearances)
        highest_id = current_id
        current_id = parent.merged_into

    # Sort by scale order then date
    chain.sort(key=lambda r: (SCALE_ORDER.get(r.scale, 99), r.date))

    # Determine which scales are covered
    covered_scales = {r.scale for r in chain}
    start_idx = SCALE_ORDER.get(link.created_scale, 0)
    expected_scales = [
        s for s in VALID_SCALES
        if SCALE_ORDER[s] >= start_idx
    ]
    missing_scales = [s for s in expected_scales if s not in covered_scales]

    return TraceResult(
        thread_id=thread_id,
        chain=chain,
        is_complete=len(missing_scales) == 0,
        missing_scales=missing_scales,
        merged_into_higher=highest_id or link.merged_into,
        child_count=len(link.child_threads),
    )


def trace_chain(state: CrossTemporalState, thread_id: str) -> list[str]:
    """Return the full upward chain of thread IDs from this thread to the top."""
    chain = [thread_id]
    link = state.links.get(thread_id)
    if link is None:
        return chain
    current_id = link.merged_into
    while current_id:
        chain.append(current_id)
        parent = state.links.get(current_id)
        if parent is None:
            break
        current_id = parent.merged_into
    return chain


# ── Query ──

def get_threads_at_scale(state: CrossTemporalState, scale: str, only_active: bool = True) -> list[CrossTemporalLink]:
    """Get all threads that have appeared in briefings at a given scale.

    If only_active=True, exclude threads that have been resolved.
    """
    results = []
    for link in state.links.values():
        if link.has_appeared_at_scale(scale):
            if only_active and link.is_resolved:
                continue
            results.append(link)
    return results


def get_unmerged_threads(state: CrossTemporalState, scale: str) -> list[CrossTemporalLink]:
    """Get threads at a scale that haven't been rolled up to the next scale yet."""
    higher = scale_higher(scale)
    if higher is None:
        return []  # Yearly is the top, nothing to roll into

    results = []
    for link in state.links.values():
        if link.created_scale != scale:
            continue
        if link.is_resolved:
            continue
        if link.merged_into is not None:
            continue  # Already rolled up
        results.append(link)
    return results


def get_thread_tree(state: CrossTemporalState, thread_id: str) -> dict:
    """Return the full tree: this thread, its children, its parent."""
    link = state.links.get(thread_id)
    if link is None:
        return {"thread": None, "parent": None, "children": []}

    parent = None
    if link.merged_into:
        parent = state.links.get(link.merged_into)

    children = [
        state.links[cid] for cid in link.child_threads
        if cid in state.links
    ]

    return {
        "thread": link,
        "parent": parent,
        "children": children,
    }


# ── Resolution ──

def resolve_thread(state: CrossTemporalState, thread_id: str, resolved_at: Optional[str] = None):
    """Mark a thread as resolved at its current scale."""
    link = state.links.get(thread_id)
    if link is None:
        return None
    link.is_resolved = True
    link.resolved_at = resolved_at or str(date.today())
    return link


def resolve_scale(state: CrossTemporalState, scale: str) -> int:
    """Mark all threads at a given scale as resolved (e.g., after weekly briefing is published)."""
    count = 0
    for link in state.links.values():
        if link.has_appeared_at_scale(scale) and not link.is_resolved:
            link.is_resolved = True
            link.resolved_at = str(date.today())
            count += 1
    return count


# ── Summary Generation ──

def generate_scale_summary(state: CrossTemporalState, scale: str) -> dict:
    """Generate statistics for a given time scale."""
    links = get_threads_at_scale(state, scale, only_active=False)
    active = [l for l in links if not l.is_resolved]
    merged_count = sum(1 for l in links if l.merged_into is not None)
    child_total = sum(len(l.child_threads) for l in links)

    return {
        "scale": scale,
        "total_threads": len(links),
        "active_threads": len(active),
        "resolved_threads": len(links) - len(active),
        "merged_up": merged_count,
        "total_children_absorbed": child_total,
        "thread_ids": [l.thread_id for l in links],
    }


def generate_full_summary(state: CrossTemporalState) -> dict:
    """Generate a multi-scale summary of the entire cross-temporal state."""
    scales = {}
    for scale in VALID_SCALES:
        scales[scale] = generate_scale_summary(state, scale)

    total_links = len(state.links)
    fully_resolved = sum(
        1 for l in state.links.values()
        if l.is_resolved and l.merged_into is None
    )

    return {
        "domain": state.domain_id,
        "total_threads": total_links,
        "fully_resolved": fully_resolved,
        "scales": scales,
    }
