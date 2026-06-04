"""Briefing context selection policies."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from stratum.db.judgment_lifecycle import JudgmentLifecyclePolicy

from stratum.subsystems.story_tracking.story_contracts import CausalEdge, EventRecord, Judgment


class ContextSelectionPolicy:
    """Select and rank story context items for briefing prompts."""

    scale_order = ["daily", "weekly", "monthly", "quarterly", "yearly"]
    active_statuses = {"emerging", "active", "cooling", "unknown"}

    def carried_forward(
        self,
        events: list[EventRecord],
        scale: str,
        target_date: str,
        lookback_days: int,
    ) -> list[dict]:
        scale_idx = self.scale_order.index(scale) if scale in self.scale_order else 0

        cutoff = (date.fromisoformat(target_date) - timedelta(days=lookback_days)).isoformat()
        lower_scales = self.scale_order[:scale_idx + 1]

        carried = []
        seen = set()

        for event in events:
            if event.status not in ("emerging", "active", "cooling"):
                continue
            if event.id in seen:
                continue

            for ref in event.scale_refs:
                ref_scale = ref.scale if hasattr(ref, "scale") else ref.get("scale", "")
                ref_date = ref.date if hasattr(ref, "date") else ref.get("date", "")
                if ref_scale in lower_scales and cutoff <= ref_date <= target_date:
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

        carried.sort(key=lambda item: item["last_date"], reverse=True)
        carried.sort(key=lambda item: item["priority"])
        return carried

    def due_judgments(
        self,
        judgments: list[Judgment],
        as_of: str,
        within_days: int,
    ) -> list[dict]:
        today = date.fromisoformat(as_of) if as_of else date.today()
        end_period = (today + timedelta(days=within_days)).isoformat()
        lifecycle = JudgmentLifecyclePolicy()
        due = []

        for judgment in judgments:
            made_at = str(getattr(judgment, "made_at", "") or "")[:10]
            if made_at and made_at > as_of:
                continue
            record = {
                "result": judgment.verdict,
                "expected_verification": judgment.expected_verification,
                "created_at": judgment.made_at,
            }
            decision = lifecycle.evaluate_due(record, end_period=end_period)
            if not decision.is_due:
                continue

            due_date = decision.due_date or str(judgment.expected_verification or "")[:10]
            expected = _parse_date(due_date) or today
            delta = (expected - today).days
            due.append({
                "judgment_id": judgment.id,
                "hypothesis": judgment.hypothesis,
                "due_date": due_date,
                "days_remaining": delta,
                "verdict": judgment.verdict,
                "target_type": judgment.target_type,
                "target_ids": judgment.target_ids,
                "due_basis": decision.basis,
            })

        due.sort(key=lambda judgment: judgment["days_remaining"])
        return due

    def coverage_gaps(
        self,
        events: list[EventRecord],
        as_of: str,
        gap_days: int,
        coverage_entities: Optional[list[str]] = None,
    ) -> list[dict]:
        today = date.fromisoformat(as_of) if as_of else date.today()

        entity_last = {}
        for event in events:
            event_date = str(event.last_updated or "")[:10]
            if event_date and event_date > as_of:
                continue
            for entity in event.entity_tags:
                if entity not in entity_last or event.last_updated > entity_last[entity]:
                    entity_last[entity] = event.last_updated

        gaps = []
        coverage_universe = []
        seen_entities = set()
        for entity in coverage_entities or []:
            entity = str(entity or "").strip()
            if entity and entity not in seen_entities:
                seen_entities.add(entity)
                coverage_universe.append(entity)

        for entity in coverage_universe:
            if entity not in entity_last:
                gaps.append({
                    "entity": entity,
                    "last_mentioned": None,
                    "days_since": None,
                    "status": "never_seen",
                })

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
                    "status": "stale",
                })

        gaps.sort(key=lambda gap: (gap["days_since"] is not None, gap["days_since"] or 0), reverse=True)
        return gaps

    def active_chains(
        self,
        edges: list[CausalEdge],
        events: list[EventRecord],
        as_of: Optional[str] = None,
    ) -> list[dict]:
        as_of_date = str(as_of or "")[:10]
        event_status = {}
        for event in events:
            event_date = str(getattr(event, "last_updated", "") or "")[:10]
            if as_of_date and event_date and event_date > as_of_date:
                continue
            event_status[event.id] = event.status

        chains = {}
        for edge in [edge for edge in edges if not edge.verified]:
            edge_date = str(getattr(edge, "created", "") or "")[:10]
            if as_of_date and edge_date and edge_date > as_of_date:
                continue
            cause_status = event_status.get(edge.cause_id, "unknown")
            effect_status = event_status.get(edge.effect_id, "unknown")
            if cause_status not in self.active_statuses and effect_status not in self.active_statuses:
                continue
            chain_key = f"{edge.cause_id}-{edge.effect_id}"
            chains[chain_key] = {
                "cause_id": edge.cause_id,
                "effect_id": edge.effect_id,
                "mechanism": edge.mechanism[:200],
                "confidence": edge.confidence,
                "created": edge.created,
                "cause_status": cause_status,
                "effect_status": effect_status,
            }

        return list(chains.values())

    def unassigned(self, events: list[EventRecord], as_of: Optional[str] = None) -> list[str]:
        as_of_date = str(as_of or "")[:10]
        unassigned = []
        for event in events:
            event_date = str(getattr(event, "last_updated", "") or "")[:10]
            if as_of_date and event_date and event_date > as_of_date:
                continue
            if len(event.scale_refs) == 0 and event.status in ("emerging", "active"):
                unassigned.append(event.id)
        return unassigned


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
