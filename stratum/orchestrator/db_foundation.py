"""Opt-in DB foundation 0.1 daily report/evidence persistence helpers."""

from __future__ import annotations

import hashlib
import json
import os
import sys

from stratum.contracts.pipeline_artifacts import EVENT_THREADS, REPORT_ARTIFACT_TYPES


def try_db_foundation_ingest(domain_id: str, run_date: str, paths: dict) -> dict:
    """Persist foundation report/evidence rows when the explicit migration exists."""
    try:
        from stratum.db.connection import get_db
        from stratum.db.persistence import (
            foundation_schema_ready,
            link_event_articles,
            upsert_articles,
            upsert_report_bundle,
        )

        conn = get_db(domain_id)
        try:
            if not foundation_schema_ready(conn):
                return {"status": "skipped", "detail": "DB foundation 0.1 tables not present"}
        finally:
            conn.close()

        articles = load_jsonl(paths.get("articles", ""))
        article_count = upsert_articles(
            domain_id,
            articles,
            run_date,
            artifact_path=paths.get("articles", ""),
        ) if articles else 0
        event_article_links = event_article_links_from_threads(event_threads_path_for(paths), run_date)
        linked_events = link_event_articles(domain_id, event_article_links) if event_article_links else 0
        report, sections, items, item_events, item_threads, item_articles = build_report_bundle(
            domain_id,
            run_date,
            paths,
        )
        bundle_stats = upsert_report_bundle(
            domain_id,
            report,
            sections=sections,
            items=items,
            item_events=item_events,
            item_threads=item_threads,
            item_articles=item_articles,
            artifacts=report_artifacts(paths),
        )
        return {"status": "success", "articles": article_count, "event_articles": linked_events, **bundle_stats}
    except Exception as exc:
        print(f"⚠️  DB foundation 0.1 ingest skipped: {exc}", file=sys.stderr)
        return {"status": "failed_nonblocking", "detail": str(exc)}


def build_report_bundle(domain_id: str, run_date: str, paths: dict) -> tuple:
    report_id = f"report-{domain_id}-daily-{run_date}"
    report = {
        "id": report_id,
        "scale": "daily",
        "period": run_date,
        "run_date": run_date,
        "markdown_path": paths.get("briefing_md", ""),
        "html_path": paths.get("briefing_html", ""),
        "pdf_path": paths.get("briefing_pdf", ""),
        "run_manifest_path": paths.get("run_manifest", ""),
    }
    sections = [
        {"section_key": "today", "title": "今日要点", "position": 1},
        {"section_key": "industry", "title": "行业要点", "position": 2},
        {"section_key": "signals", "title": "产业信号", "position": 3},
        {"section_key": "focus", "title": "特别关注", "position": 4},
        {"section_key": "contrarian", "title": "反向信号", "position": 5},
    ]
    plan = load_json_object(paths.get("briefing_plan", ""))
    chunks = load_json_list(paths.get("briefing_chunks", ""))
    written_items = {
        item.get("item_id"): item
        for block in chunks
        for item in block.get("items", []) or []
        if item.get("item_id")
    }
    items, item_events, item_threads, item_articles = [], [], [], []
    position_by_section = {"industry": 0, "signals": 0}
    for planned in plan.get("items", []) or []:
        _append_report_item(
            report_id,
            run_date,
            planned,
            written_items.get(planned.get("item_id"), {}),
            position_by_section,
            items,
            item_events,
            item_threads,
            item_articles,
        )
    return report, sections, items, item_events, item_threads, item_articles


def _append_report_item(
    report_id,
    run_date,
    planned,
    written,
    position_by_section,
    items,
    item_events,
    item_threads,
    item_articles,
) -> None:
    item_id = planned.get("item_id")
    if not item_id:
        return
    section_key = "signals" if planned.get("kind") == "edge" else "industry"
    position_by_section[section_key] += 1
    report_item_id = f"{report_id}-{item_id}"
    paragraphs = written.get("paragraphs") or []
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    title = str(written.get("title") or planned.get("title_hint") or "").strip()
    items.append({
        "id": report_item_id,
        "section_key": section_key,
        "position": position_by_section[section_key],
        "title": title,
        "body": "\n\n".join(str(p).strip() for p in paragraphs if str(p).strip()),
        "signal_type": planned.get("kind", ""),
        "importance": int(planned.get("sequence") or position_by_section[section_key]),
        "confidence": "B",
    })
    thread_id = planned.get("thread_id")
    if thread_id:
        item_threads.append({"report_item_id": report_item_id, "thread_id": thread_id})
        item_events.append({"report_item_id": report_item_id, "event_id": f"ev-{run_date}-{thread_id}"})
    for article_id in planned.get("article_ids", []) or []:
        if article_id:
            item_articles.append({
                "report_item_id": report_item_id,
                "article_id": str(article_id),
                "source_line": title,
            })


def report_artifacts(paths: dict) -> list[dict]:
    artifact_keys = [
        *REPORT_ARTIFACT_TYPES.items(),
        ("briefing_md", "markdown"),
        ("briefing_html", "html"),
        ("briefing_pdf", "pdf"),
    ]
    artifacts = []
    for key, artifact_type in artifact_keys:
        path = paths.get(key, "")
        if not path:
            continue
        if not os.path.exists(path):
            if artifact_type != "run_manifest":
                continue
            sha256 = ""
        else:
            sha256 = file_sha256(path)
        artifacts.append({"artifact_type": artifact_type, "path": path, "sha256": sha256})
    event_threads = event_threads_path_for(paths)
    if os.path.exists(event_threads):
        artifacts.append({
            "artifact_type": "event_threads",
            "path": event_threads,
            "sha256": file_sha256(event_threads),
        })
    return artifacts


def load_jsonl(path: str) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
    return rows


def load_json_object(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def load_json_list(path: str) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def event_threads_path_for(paths: dict) -> str:
    event_threads_path = os.path.join(paths["data_dir"], EVENT_THREADS.filename)
    if os.path.exists(event_threads_path):
        return event_threads_path
    alt_path = os.path.join(paths["data_dir"], "..", "event-threads", EVENT_THREADS.filename)
    return alt_path if os.path.exists(alt_path) else event_threads_path


def event_article_links_from_threads(event_threads_path: str, run_date: str) -> list[dict]:
    payload = load_json_object(event_threads_path)
    links = []
    for thread in payload.get("threads", []) or []:
        thread_id = thread.get("thread_id") or thread.get("id")
        if not thread_id:
            continue
        for article_id in thread.get("article_ids", []) or []:
            if article_id:
                links.append({"event_id": f"ev-{run_date}-{thread_id}", "article_id": str(article_id)})
    return links


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
