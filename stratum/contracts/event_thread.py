"""Cross-temporal event linkage contracts — v0.1.0.

Links event threads across briefing time scales:
  daily → weekly → monthly → quarterly → yearly

Each scale has its own synthesis, prominence, and parent/child relationships.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ── Time Scales ──

VALID_SCALES = ("daily", "weekly", "monthly", "quarterly", "yearly")

SCALE_ORDER = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "yearly": 4}


def scale_higher(scale: str) -> Optional[str]:
    """Return the next-higher time scale, or None if at the top."""
    order = SCALE_ORDER.get(scale)
    if order is None or order >= 4:
        return None
    return ("daily", "weekly", "monthly", "quarterly", "yearly")[order + 1]


def scale_lower(scale: str) -> Optional[str]:
    """Return the next-lower time scale, or None if at the bottom."""
    order = SCALE_ORDER.get(scale)
    if order is None or order <= 0:
        return None
    return ("daily", "weekly", "monthly", "quarterly", "yearly")[order - 1]


# ── Briefing Reference ──

@dataclass
class BriefingRef:
    """A record that a thread appeared in a specific briefing at a specific scale."""
    briefing_id: str           # e.g. "daily-2026-05-28", "weekly-2026-W22"
    scale: str                 # daily | weekly | monthly | quarterly | yearly
    date: str                  # ISO date the briefing was generated for
    section: str               # Which section/story in the briefing
    prominence: str            # lead | supporting | mentioned
    synthesis: str             # How the event was summarized at this scale (300 chars max)

    def __post_init__(self):
        if self.scale not in VALID_SCALES:
            raise ValueError(f"Invalid scale: {self.scale}. Must be one of {VALID_SCALES}")


# ── Cross-Temporal Link ──

@dataclass
class CrossTemporalLink:
    """Vertical linkage for a single event thread across time scales.

    A daily thread gets a CrossTemporalLink record. When it appears in a weekly briefing,
    a new BriefingRef is appended. When weekly briefings roll up into monthly, the
    weekly thread's link gets a child reference pointing to the daily thread.
    """
    thread_id: str
    created_scale: str         # The scale at which this thread was first created
    appearances: list[BriefingRef] = field(default_factory=list)
    merged_into: Optional[str] = None    # thread_id at next-higher scale (if rolled up)
    child_threads: list[str] = field(default_factory=list)  # thread_ids from lower scales merged here
    is_resolved: bool = False            # True when this scale's resolution is final
    resolved_at: Optional[str] = None    # ISO date when resolved
    narrative: str = ""                  # Accumulated narrative across scales (LLM-generated)

    def add_appearance(self, ref: BriefingRef):
        """Add or replace a briefing appearance, maintaining chronological order."""
        self.appearances = [
            existing for existing in self.appearances
            if not (
                existing.scale == ref.scale
                and existing.briefing_id == ref.briefing_id
            )
        ]
        self.appearances.append(ref)
        self.appearances.sort(key=lambda r: r.date)

    def get_appearances_at_scale(self, scale: str) -> list[BriefingRef]:
        """Return all appearances at a given scale."""
        return [r for r in self.appearances if r.scale == scale]

    def has_appeared_at_scale(self, scale: str) -> bool:
        """Check if this thread has appeared in at least one briefing at the given scale."""
        return any(r.scale == scale for r in self.appearances)


# ── Cross-Temporal Engine Input/Output ──

@dataclass
class RegisterInput:
    """Input for registering a briefing appearance."""
    thread_id: str
    briefing_id: str
    scale: str
    date: str
    section: str
    prominence: str            # lead | supporting | mentioned
    synthesis: str


@dataclass
class RollupInput:
    """Input for rolling up lower-scale threads into a higher-scale thread."""
    source_thread_ids: list[str]     # threads at lower scale
    target_thread_id: str            # thread at higher scale
    target_scale: str                # e.g. "weekly"
    briefing_id: str
    date: str
    synthesis: str                   # How the rollup synthesizes the lower-scale threads


@dataclass
class CrossTemporalState:
    """Full cross-temporal registry for a domain."""
    domain_id: str
    links: dict[str, CrossTemporalLink] = field(default_factory=dict)

    def get_link(self, thread_id: str) -> Optional[CrossTemporalLink]:
        return self.links.get(thread_id)

    def get_or_create_link(self, thread_id: str, created_scale: str = "daily") -> CrossTemporalLink:
        if thread_id not in self.links:
            self.links[thread_id] = CrossTemporalLink(
                thread_id=thread_id,
                created_scale=created_scale,
            )
        return self.links[thread_id]


# ── Trace Result ──

@dataclass
class TraceResult:
    """Result of tracing a thread across all time scales."""
    thread_id: str
    chain: list[BriefingRef]         # appearances ordered by scale and date
    is_complete: bool                 # True if appears at all expected scales
    missing_scales: list[str]         # scales where this thread hasn't appeared
    merged_into_higher: Optional[str] # thread_id of the higher-scale parent
    child_count: int                  # number of lower-scale threads merged into this one
