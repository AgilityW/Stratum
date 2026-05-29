"""Validation gates for agent-generated proposals.

Every agent-generated object must pass its gate before entering the store.
Gates are pure functions: they take a proposal + existing data, return a verdict.

GateResult.passed=True → safe to write
GateResult.passed=False → return errors to agent for correction
"""

from dataclasses import dataclass, field
from typing import Optional

from story_contracts import EventRecord, CausalEdge, Judgment


# ── Gate Result ──

@dataclass
class GateResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ok(warnings: list[str] = None) -> GateResult:
    return GateResult(passed=True, warnings=warnings or [])


def fail(errors: list[str], warnings: list[str] = None) -> GateResult:
    return GateResult(passed=False, errors=errors, warnings=warnings or [])


# ── Event Gate ──

def gate_event(event: EventRecord, existing_events: list[EventRecord]) -> GateResult:
    """Validate a proposed EventRecord before insertion.

    Checks:
      1. Required fields non-empty (id, title, canonical_question, created)
      2. ID format: event-{domain}-{seq}
      3. No duplicate title (same day)
      4. Priority in [1,5]
      5. Status is valid
      6. topic_tags and entity_tags are non-empty (warning only)
    """
    errors = []
    warnings = []

    # Required fields
    if not event.id or not event.id.strip():
        errors.append("id is required")
    if not event.title or not event.title.strip():
        errors.append("title is required")
    if not event.canonical_question or not event.canonical_question.strip():
        errors.append("canonical_question is required")
    if not event.created:
        errors.append("created date is required")

    # ID format
    if event.id and not event.id.startswith("event-"):
        errors.append(f"id must start with 'event-', got '{event.id}'")

    # Priority range
    if not (1 <= event.priority <= 5):
        errors.append(f"priority must be 1-5, got {event.priority}")

    # Valid status
    VALID_STATUSES = ("emerging", "active", "cooling", "resolved", "archived")
    if event.status not in VALID_STATUSES:
        errors.append(f"status must be one of {VALID_STATUSES}, got '{event.status}'")

    # Duplicate detection: same title, same day
    if event.title and event.created:
        for existing in existing_events:
            if existing.title == event.title and existing.created[:10] == event.created[:10] and existing.id != event.id:
                warnings.append(f"duplicate title '{event.title}' on {event.created[:10]} (existing: {existing.id})")

    # Tag warnings
    if not event.topic_tags:
        warnings.append("topic_tags is empty — event may be hard to discover")
    if not event.entity_tags:
        warnings.append("entity_tags is empty — event won't appear in entity queries")

    return fail(errors, warnings) if errors else ok(warnings)


# ── Causal Edge Gate ──

def gate_causal_edge(
    edge: CausalEdge,
    existing_edges: list[CausalEdge],
    event_ids: set[str],
) -> GateResult:
    """Validate a proposed CausalEdge.

    Checks:
      1. Required fields non-empty
      2. cause_id and effect_id exist in the event store
      3. cause_id ≠ effect_id (no self-loops)
      4. mechanism is non-empty and ≥ 10 chars
      5. No duplicate edge (same cause_id + effect_id)
      6. No transitive redundancy warning (A→B + B→C may make A→C redundant)
    """
    errors = []
    warnings = []

    if not edge.id or not edge.id.startswith("causal-"):
        errors.append(f"id must start with 'causal-', got '{edge.id}'")
    if not edge.cause_id:
        errors.append("cause_id is required")
    if not edge.effect_id:
        errors.append("effect_id is required")
    if not edge.mechanism or len(edge.mechanism.strip()) < 10:
        errors.append("mechanism must be at least 10 characters")
    if not edge.created:
        errors.append("created date is required")

    # Self-loop
    if edge.cause_id and edge.effect_id and edge.cause_id == edge.effect_id:
        errors.append(f"self-loop detected: cause_id and effect_id are both '{edge.cause_id}'")

    # Referenced events must exist
    if edge.cause_id and edge.cause_id not in event_ids:
        errors.append(f"cause_id '{edge.cause_id}' does not exist in event store")
    if edge.effect_id and edge.effect_id not in event_ids:
        errors.append(f"effect_id '{edge.effect_id}' does not exist in event store")

    # Duplicate edge
    if edge.cause_id and edge.effect_id:
        for existing in existing_edges:
            if existing.cause_id == edge.cause_id and existing.effect_id == edge.effect_id:
                warnings.append(f"duplicate edge {edge.cause_id}→{edge.effect_id} (existing: {existing.id})")

    # Transitive redundancy: if A→B and B→C exist, A→C may be redundant
    if edge.cause_id and edge.effect_id:
        for e1 in existing_edges:
            if e1.cause_id == edge.cause_id:
                for e2 in existing_edges:
                    if e2.cause_id == e1.effect_id and e2.effect_id == edge.effect_id:
                        warnings.append(
                            f"possible transitive redundancy: {edge.cause_id}→{e1.effect_id}→{edge.effect_id} already exists")

    # Confidence
    if edge.confidence not in ("A", "B", "C"):
        errors.append(f"confidence must be A/B/C, got '{edge.confidence}'")

    return fail(errors, warnings) if errors else ok(warnings)


# ── Judgment Gate ──

def gate_judgment(
    judgment: Judgment,
    existing_judgments: list[Judgment],
) -> GateResult:
    """Validate a proposed Judgment.

    Checks:
      1. Required fields non-empty
      2. target_type is 'entity' or 'event_pair'
      3. target_ids matches target_type (1 for entity, 2 for event_pair)
      4. hypothesis ≥ 20 chars
      5. confidence is A/B/C
      6. expected_verification is a valid date after made_at
      7. No duplicate hypothesis (same target + same text)
    """
    errors = []
    warnings = []

    if not judgment.id or not judgment.id.startswith("judgment-"):
        errors.append(f"id must start with 'judgment-', got '{judgment.id}'")
    if judgment.target_type not in ("entity", "event_pair"):
        errors.append(f"target_type must be 'entity' or 'event_pair', got '{judgment.target_type}'")
    if not judgment.target_ids:
        errors.append("target_ids is required")
    if judgment.target_type == "entity" and len(judgment.target_ids) != 1:
        errors.append(f"entity judgment requires exactly 1 target_id, got {len(judgment.target_ids)}")
    if judgment.target_type == "event_pair" and len(judgment.target_ids) != 2:
        errors.append(f"event_pair judgment requires exactly 2 target_ids, got {len(judgment.target_ids)}")
    if not judgment.hypothesis or len(judgment.hypothesis.strip()) < 20:
        errors.append("hypothesis must be at least 20 characters")
    if judgment.confidence not in ("A", "B", "C"):
        errors.append(f"confidence must be A/B/C, got '{judgment.confidence}'")
    if not judgment.made_at:
        errors.append("made_at date is required")
    if not judgment.expected_verification:
        errors.append("expected_verification date is required")

    # Date ordering: expected_verification should be after made_at
    if judgment.made_at and judgment.expected_verification:
        if judgment.expected_verification < judgment.made_at:
            errors.append(
                f"expected_verification ({judgment.expected_verification}) is before made_at ({judgment.made_at})")

    # Verdict validation
    VALID_VERDICTS = ("pending", "correct", "incorrect", "partial", "deferred", "unverifiable")
    if judgment.verdict not in VALID_VERDICTS:
        errors.append(f"verdict must be one of {VALID_VERDICTS}, got '{judgment.verdict}'")

    # Duplicate hypothesis
    if judgment.hypothesis:
        for existing in existing_judgments:
            if (existing.target_type == judgment.target_type
                and existing.target_ids == judgment.target_ids
                and existing.hypothesis.strip().lower() == judgment.hypothesis.strip().lower()
                and existing.id != judgment.id):
                warnings.append(f"duplicate hypothesis for same target (existing: {existing.id})")

    # Empty triggered_by_events warning
    if not judgment.triggered_by_events:
        warnings.append("triggered_by_events is empty — judgment has no evidence anchor")

    return fail(errors, warnings) if errors else ok(warnings)


# ── Batch Gate ──

def gate_batch(
    events: list[EventRecord] = None,
    edges: list[CausalEdge] = None,
    judgments: list[Judgment] = None,
    existing_events: list[EventRecord] = None,
    existing_edges: list[CausalEdge] = None,
    existing_judgments: list[Judgment] = None,
) -> dict[str, list[GateResult]]:
    """Validate a batch of proposals together.

    Returns {"events": [...], "edges": [...], "judgments": [...]}
    """
    existing_events = existing_events or []
    existing_edges = existing_edges or []
    existing_judgments = existing_judgments or []

    event_ids = {e.id for e in existing_events}
    if events:
        event_ids.update({e.id for e in events})

    results = {
        "events": [gate_event(e, existing_events) for e in (events or [])],
        "edges": [gate_causal_edge(e, existing_edges, event_ids) for e in (edges or [])],
        "judgments": [gate_judgment(j, existing_judgments) for j in (judgments or [])],
    }
    return results


def batch_passed(results: dict) -> bool:
    """Check if all gates in a batch result passed."""
    for category in results.values():
        for r in category:
            if not r.passed:
                return False
    return True
