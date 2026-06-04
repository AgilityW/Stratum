"""Story context and normalize-feedback helpers for daily orchestration."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import yaml


CST = timezone(timedelta(hours=8))


def coverage_entities_from_domain_config(domain_config_path: str) -> list[str]:
    """Load domain entities that should be considered for coverage gaps."""
    try:
        with open(domain_config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []

    entities: list[str] = []
    seen: set[str] = set()
    for company in cfg.get("companies", []) or []:
        entity_id = str(company.get("id") or "").strip()
        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            entities.append(entity_id)
    return entities


def try_generate_story_context(domain_id: str, run_date: str, paths: dict, output_path: str):
    """Generate BriefingContext for the agent, from SQLite story-tracking data."""
    try:
        from types import SimpleNamespace
        from stratum.db.service import get_story_context_records
        from stratum.subsystems.story_tracking import generate_context

        coverage_entities = coverage_entities_from_domain_config(paths.get("domain_config", ""))
        records = get_story_context_records(domain_id)
        if not records["events"] and not coverage_entities:
            return

        events = []
        for row in records["events"]:
            entity_ids = row.get("entity_ids") or []
            events.append(SimpleNamespace(
                id=row["id"],
                thread_id=row.get("thread_id") or "",
                title=row.get("title") or "",
                status=row.get("status") or "emerging",
                priority=row.get("priority") or 3,
                entity_tags=entity_ids,
                last_updated=row.get("date") or run_date,
                scale_refs=[{
                    "scale": row.get("scale"),
                    "date": row.get("date"),
                    "briefing_id": row.get("briefing_id"),
                }] if row.get("scale") else [],
                open_questions=[],
            ))

        thread_event = {}
        for event in events:
            tid = event.thread_id or event.id
            if tid not in thread_event or event.last_updated > thread_event[tid][1]:
                thread_event[tid] = (event.id, event.last_updated)

        edges = []
        for row in records["causal_edges"]:
            cause_thread_id = row.get("cause_thread_id") or ""
            effect_thread_id = row.get("effect_thread_id") or ""
            cause_id = thread_event.get(cause_thread_id, (cause_thread_id,))[0]
            effect_id = thread_event.get(effect_thread_id, (effect_thread_id,))[0]
            edges.append(SimpleNamespace(
                id=row["id"],
                cause_id=cause_id,
                effect_id=effect_id,
                mechanism=row.get("mechanism") or "",
                confidence=row.get("confidence") or "B",
                created=row.get("created_at") or run_date,
                verified=bool(row.get("verified")),
            ))

        judgments = []
        for row in records["judgments"]:
            target_ids = row.get("target_entity_ids") or []
            if not target_ids:
                target_ids = row.get("target_thread_ids") or []
            verdict_map = {
                None: "pending",
                "pending": "pending",
                "correct": "correct",
                "incorrect": "incorrect",
                "partially_correct": "deferred",
            }
            judgments.append(SimpleNamespace(
                id=row["id"],
                target_type=row.get("target_type") or "entity",
                target_ids=target_ids,
                hypothesis=row.get("hypothesis") or "",
                confidence=row.get("confidence") or "B",
                expected_verification=row.get("expected_verification") or run_date,
                verdict=verdict_map.get(row.get("result"), "pending"),
                made_at=row.get("created_at") or run_date,
            ))

        ctx = generate_context(
            domain_id,
            "daily",
            run_date,
            events,
            edges,
            judgments,
            coverage_entities=coverage_entities,
        )
        with open(output_path, "w") as f:
            json.dump({
                "scale": ctx.scale,
                "date": ctx.date,
                "domain_id": ctx.domain_id,
                "carried_forward": ctx.carried_forward,
                "due_judgments": ctx.due_judgments,
                "coverage_gaps": ctx.coverage_gaps,
                "active_causal_chains": ctx.active_causal_chains,
                "unassigned_events": ctx.unassigned_events,
            }, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n📋 Story context written: {output_path} "
              f"({len(ctx.carried_forward)} carried, {len(ctx.due_judgments)} due, "
              f"{len(ctx.coverage_gaps)} gaps)", file=sys.stderr)
    except Exception as exc:
        print(f"⚠️  Story context generation skipped: {exc}", file=sys.stderr)


def export_thread_keywords(domain_id: str, paths: dict):
    """Export thread_keywords.json from SQLite events table."""
    try:
        from stratum.db.service import get_thread_keyword_events

        rows = get_thread_keyword_events(domain_id)
        if not rows:
            return

        threads_by_id = {}
        for row in rows:
            title = row.get("title") or ""
            thread_id = row.get("thread_id") or row["id"]
            thread = threads_by_id.setdefault(thread_id, {
                "thread_id": thread_id,
                "label": title or row["id"],
                "status": row.get("status") or "active",
                "keywords": set(),
                "description": "",
            })
            if title and (not thread["label"] or thread["label"] == thread_id):
                thread["label"] = title
            thread["status"] = merge_thread_export_status(thread["status"], row.get("status") or "active")
            thread["keywords"].update(keywords_from_thread_event(title, row.get("entity_ids")))

        threads = [{**thread, "keywords": sorted(thread["keywords"])[:20]} for thread in threads_by_id.values()]
        if not threads:
            return

        output_path = paths["thread_keywords"]
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump({"threads": threads, "exported_at": datetime.now(CST).isoformat()},
                      f, ensure_ascii=False, indent=2)

        print(f"\n🔗 Thread keywords exported: {len(threads)} threads → {output_path}",
              file=sys.stderr)
        for thread in threads:
            print(f"   [{thread['status']}] {thread['label'][:60]} ({len(thread['keywords'])} keywords)",
                  file=sys.stderr)
    except Exception as exc:
        print(f"⚠️  Thread keywords export skipped: {exc}", file=sys.stderr)


def keywords_from_thread_event(title: str, entity_ids_value) -> set[str]:
    """Extract stable matching keywords from one persisted event row."""
    keywords = set()
    if title:
        tokens = re.findall(r'[A-Za-z0-9]+|[\u4e00-\u9fff]+', title)
        for token in tokens:
            token = token.lower().strip()
            if len(token) >= 2:
                keywords.add(token)
            if re.search(r'[\u4e00-\u9fff]', token) and len(token) >= 8:
                cjk = re.findall(r'[\u4e00-\u9fff]', token)
                for i in range(len(cjk) - 1):
                    keywords.add(''.join(cjk[i:i + 2]))

    try:
        entity_ids = entity_ids_value if isinstance(entity_ids_value, list) else json.loads(entity_ids_value or "[]")
    except (TypeError, json.JSONDecodeError):
        entity_ids = []
    keywords.update(entity.lower() for entity in entity_ids if entity)
    return keywords


def merge_thread_export_status(current: str, incoming: str) -> str:
    """Keep the most actionable lifecycle status for normalize feedback."""
    rank = {"active": 0, "emerging": 1, "pending": 2, "cooling": 3}
    return incoming if rank.get(incoming or "", 99) < rank.get(current or "", 99) else current
