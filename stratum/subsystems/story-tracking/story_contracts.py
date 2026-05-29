"""Story-tracking subsystem — data contracts v1.0.

Multi-dimensional event intelligence:
  - EventStore: flat event records with topic/entity tags + scale references
  - CausalGraph: directed cause → effect edges between events
  - JudgmentLog: hypotheses about entities or causal relationships + verification

Storage path: {config.output_dir}/{domain}/data/story-tracking/
  events.jsonl   — one EventRecord per line
  causal.jsonl   — one CausalEdge per line
  judgments.jsonl — one Judgment per line
  state.json     — metadata (seq counters, last write timestamps)

All dates are ISO 8601 strings ("2026-05-29" or "2026-05-29T08:00:00+08:00").
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════

class Verdict(Enum):
    """Six-state judgment verification result."""
    PENDING = "pending"
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"           # Direction right, magnitude/timing off
    DEFERRED = "deferred"         # Verification window extended
    UNVERIFIABLE = "unverifiable" # No public data available to verify


class Scale(str, Enum):
    """Briefing time scales."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

    @classmethod
    def order(cls, scale: str) -> int:
        mapping = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "yearly": 4}
        return mapping.get(scale, -1)


class UpdateType(str, Enum):
    """How a timeline entry updates the event narrative."""
    FIRST_DISCLOSURE = "first_disclosure"
    CONFIRMATION = "confirmation"
    CONTRADICTION = "contradiction"
    QUANTIFICATION = "quantification"
    REHASH = "rehash"


class Prominence(str, Enum):
    """How prominently an event appears in a briefing."""
    LEAD = "lead"
    SUPPORTING = "supporting"
    MENTIONED = "mentioned"


# ═══════════════════════════════════════════════════
# Core Data Models
# ═══════════════════════════════════════════════════

@dataclass
class TimelineEntry:
    """A single point on an event's day-to-day timeline."""
    date: str                          # ISO date
    update_type: UpdateType
    summary: str                       # ≤ 300 chars
    confidence: str                    # A | B | C
    source_ids: list[str] = field(default_factory=list)


@dataclass
class ScaleRef:
    """Records that an event appeared in a briefing at a specific scale."""
    scale: str                         # daily | weekly | monthly | quarterly | yearly
    briefing_id: str                   # e.g. "daily-2026-05-29", "weekly-2026-W22"
    date: str                          # ISO date the briefing covers
    prominence: Prominence
    synthesis: str                     # How the event was summarized at this scale


@dataclass
class EventRecord:
    """A single event — the fundamental unit of the event store.

    An event is a discrete, named occurrence in the world. It carries:
    - topic_tags: what themes does it relate to (e.g. "HBM", "NAND pricing")
    - entity_tags: which entities are involved (e.g. "Samsung", "NVIDIA")
    - timeline: day-to-day evolution of the event
    - scale_refs: which briefings (daily/weekly/...) this appeared in
    - identity fields: for multi-source dedup (canonical_id, parent_event, child_events)
    - date fields: occurred_at (event date), first_reported_at (collection date)
    """
    id: str                            # event-{domain}-{seq:04d}
    title: str
    canonical_question: str            # What question does this event answer?
    created: str                       # ISO date first added to store
    last_updated: str                  # ISO date last modified

    # Tags — flat, multi-value
    topic_tags: list[str] = field(default_factory=list)    # ["HBM", "memory interface"]
    entity_tags: list[str] = field(default_factory=list)   # ["Samsung", "NVIDIA"]

    # Timeline — day-by-day updates
    timeline: list[TimelineEntry] = field(default_factory=list)

    # Cross-temporal — which briefings this appeared in
    scale_refs: list[ScaleRef] = field(default_factory=list)

    # Identity resolution — for multi-source dedup
    canonical_id: Optional[str] = None    # Points to the authoritative version
    parent_event: Optional[str] = None    # If this is a sub-event of another
    child_events: list[str] = field(default_factory=list)  # Sub-events merged here
    source_ids: list[str] = field(default_factory=list)    # Originating source article IDs
    thread_id: Optional[str] = None                         # Agent EventThread ID for idempotent bridge

    # Date precision — multiple date facets
    occurred_at: Optional[str] = None        # When the event actually happened
    first_reported_at: Optional[str] = None   # When first collected by the system

    # Status — lifecycle
    status: str = "emerging"             # emerging | active | cooling | resolved | archived
    priority: int = 3                    # 1 (highest) - 5 (lowest)

    # LLM-generated fields
    current_assessment: str = ""          # Latest synthesis across all sources
    open_questions: list[str] = field(default_factory=list)
    watch_signals: list[str] = field(default_factory=list)


@dataclass
class CausalEdge:
    """A directed causal relationship between two events.

    cause_id → effect_id, with a mechanism that explains why.
    Each edge is itself a testable hypothesis (linked to JudgmentLog).
    """
    id: str                            # causal-{domain}-{seq:04d}
    cause_id: str                      # event_id of the cause
    effect_id: str                     # event_id of the effect
    mechanism: str                     # Why does cause lead to effect? (≤ 500 chars)
    confidence: str                    # A | B | C
    created: str                       # ISO date
    verified: bool = False             # Has this causal link been verified?
    verified_at: Optional[str] = None
    judgment_id: Optional[str] = None  # Linked judgment if tracked separately


@dataclass
class Judgment:
    """A testable hypothesis about an entity or causal relationship.

    target_type: "entity" or "event_pair"
    For entity judgments: target_ids = [entity_id]
    For causal judgments: target_ids = [cause_event_id, effect_event_id]
    """
    id: str                            # judgment-{domain}-{seq:04d}
    target_type: str                   # "entity" | "event_pair"
    target_ids: list[str]              # Entity IDs or event pair [cause, effect]
    hypothesis: str                    # The claim being tested (≤ 500 chars)
    confidence: str                    # A | B | C
    made_at: str                       # ISO date judgment was made
    expected_verification: str         # ISO date when we expect to verify
    verdict: str = "pending"           # One of Verdict values
    verified_at: Optional[str] = None
    evidence: str = ""                 # What confirmed or refuted the judgment
    triggered_by_events: list[str] = field(default_factory=list)  # Event IDs that prompted this judgment


# ═══════════════════════════════════════════════════
# Taxonomy (Domain-specific, loaded from domains/{id}/taxonomy.yaml)
# ═══════════════════════════════════════════════════

@dataclass
class TaxonomyEntry:
    """A controlled vocabulary entry — either a topic or an entity."""
    id: str
    label: str
    type: str                          # "topic" | "company" | "person" | "technology" | "product"
    aliases: list[str] = field(default_factory=list)
    parent: Optional[str] = None       # Taxonomy hierarchy (topic ⊂ parent_topic)
    description: str = ""


# ═══════════════════════════════════════════════════
# Briefing Context (for agent interface)
# ═══════════════════════════════════════════════════

@dataclass
class BriefingContext:
    """What the agent needs to know before generating the next briefing.

    Generated by the briefing_context module. Injected into the agent prompt.
    """
    scale: str                         # Which scale briefing is being generated
    date: str                          # The target date
    domain_id: str

    # Active threads from last briefing
    carried_forward: list[dict]        # [{event_id, title, last_update, current_status}]

    # Judgments due for verification soon
    due_judgments: list[dict]          # [{judgment_id, hypothesis, due_date, days_remaining}]

    # Entities with coverage gaps
    coverage_gaps: list[dict]          # [{entity, last_mentioned, days_since}]

    # Causal chains that need updates
    active_causal_chains: list[dict]   # [{root_event, chain_length, last_updated}]

    # New events since last briefing (not yet in any briefing)
    unassigned_events: list[str]       # event_ids


# ═══════════════════════════════════════════════════
# Serialization helpers
# ═══════════════════════════════════════════════════

def _serialize(obj):
    """Convert dataclass to JSON-serializable dict, handling enums."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


def to_jsonl_line(obj) -> str:
    """Convert a dataclass to a JSONL line (no trailing newline)."""
    import json
    return json.dumps(_serialize(obj), ensure_ascii=False)


def from_jsonl_line(line: str, cls):
    """Parse a JSONL line into a dataclass instance."""
    import json
    data = json.loads(line)
    # Handle enum fields by converting strings back
    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    return cls(**data)
