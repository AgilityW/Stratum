"""Semantic read-model algorithms for DB service APIs."""

from __future__ import annotations

from typing import Any


class TrendReadModel:
    """Build deterministic trend and timeline views from already-loaded rows."""

    def rank_counts(self, counts: dict[str, int]) -> list[dict[str, Any]]:
        return [
            {"id": key, "count": value}
            for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def sort_key_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(events, key=lambda event: (int(event.get("priority") or 999), event.get("date") or ""))

    def trend_summary(
        self,
        *,
        domain: str,
        scale: str,
        start_period: str,
        end_period: str,
        events: list[dict[str, Any]],
        judgments: list[dict[str, Any]],
        key_event_limit: int = 10,
    ) -> dict[str, Any]:
        thread_counts: dict[str, int] = {}
        entity_counts: dict[str, int] = {}
        term_counts: dict[str, int] = {}
        for event in events:
            thread_id = event.get("thread_id")
            if thread_id:
                thread_counts[thread_id] = thread_counts.get(thread_id, 0) + 1
            for entity_id in event.get("entity_ids", []):
                entity_counts[entity_id] = entity_counts.get(entity_id, 0) + 1
            for term_id in event.get("term_ids", []):
                term_counts[term_id] = term_counts.get(term_id, 0) + 1

        return {
            "domain": domain,
            "scale": scale,
            "window": {"start": start_period, "end": end_period},
            "event_count": len(events),
            "top_threads": self.rank_counts(thread_counts),
            "top_entities": self.rank_counts(entity_counts),
            "top_terms": self.rank_counts(term_counts),
            "judgment_counts": JudgmentStatusReadModel().counts(judgments),
            "key_events": self.key_events(events, limit=key_event_limit),
        }

    def key_events(self, events: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
        return self.sort_key_events(events)[:limit]

    def key_timeline(
        self,
        events: list[dict[str, Any]],
        *,
        limit_per_period: int = 5,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in self.sort_key_events(events):
            grouped.setdefault(event.get("date") or "", []).append(event)
        return [
            {
                "period": period,
                "event_count": len(period_events),
                "events": period_events[:limit_per_period],
                "titles": [event.get("title", "") for event in period_events[:limit_per_period]],
            }
            for period, period_events in sorted(grouped.items())
        ]


class JudgmentStatusReadModel:
    """Build deterministic judgment status views from loaded judgment rows."""

    def group(self, judgments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for judgment in judgments:
            result = judgment.get("result") or "pending"
            grouped.setdefault(result, []).append(judgment)
        return grouped

    def counts(self, judgments: list[dict[str, Any]]) -> dict[str, int]:
        return {key: len(value) for key, value in self.group(judgments).items()}

    def status(
        self,
        *,
        domain: str,
        scale: str | None,
        start_period: str | None,
        end_period: str | None,
        judgments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        grouped = self.group(judgments)
        return {
            "domain": domain,
            "scale": scale,
            "window": {"start": start_period, "end": end_period},
            "counts": {key: len(value) for key, value in grouped.items()},
            "judgments": grouped,
        }


class EvidenceDetailReadModel:
    """Build evidence detail views from already-loaded report item rows."""

    def report_item_evidence(
        self,
        *,
        report_item_id: str,
        item: dict[str, Any] | None,
        events: list[dict[str, Any]],
        articles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "report_item_id": report_item_id,
            "item": item,
            "events": events,
            "articles": articles,
        }


class TrackingReadModel:
    """Build entity and technology tracking views from already-loaded events."""

    def filter_json_member(
        self,
        events: list[dict[str, Any]],
        *,
        column: str,
        member_id: str,
        order: str = "DESC",
    ) -> list[dict[str, Any]]:
        ordered = list(events)
        if order.upper() == "DESC":
            ordered = list(reversed(ordered))
        return [event for event in ordered if member_id in event.get(column, [])]

    def entity_timeline(
        self,
        *,
        entity_id: str,
        snapshots: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {"entity_id": entity_id, "snapshots": snapshots, "events": events}

    def technology_progress(
        self,
        *,
        term_id: str,
        events: list[dict[str, Any]],
        entity_ids: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        del term_id
        allowed = set(entity_ids) if entity_ids else None
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            for entity_id in event.get("entity_ids", []):
                if allowed is not None and entity_id not in allowed:
                    continue
                grouped.setdefault(entity_id, []).append(event)
        return grouped
