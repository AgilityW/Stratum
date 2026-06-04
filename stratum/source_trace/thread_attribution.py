"""Attribute source evidence to DB events and story threads."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def attribute_threads(
    articles: list[dict[str, Any]],
    events: list[dict[str, Any]],
    threads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build source -> event -> thread contribution records."""
    threads = threads or []
    thread_titles = {
        str(thread.get("id") or thread.get("thread_id") or ""): thread.get("title") or thread.get("name") or ""
        for thread in threads
    }
    articles_by_id = {
        str(article.get("id") or article.get("article_id") or ""): article
        for article in articles
    }
    source_threads: dict[str, dict[str, Any]] = defaultdict(lambda: {"threads": defaultdict(_thread_row)})

    for event in events:
        article_ids = _list(event.get("article_ids") or event.get("articles") or event.get("evidence_article_ids"))
        event_sources = set()
        for article_id in article_ids:
            article = articles_by_id.get(str(article_id))
            if article:
                event_sources.add(_source(article))
        if not event_sources:
            event_sources.add(_source(event))

        thread_id = str(event.get("thread_id") or event.get("story_thread_id") or "unassigned")
        for source in event_sources:
            row = source_threads[source]["threads"][thread_id]
            row["thread_id"] = thread_id
            row["thread_title"] = thread_titles.get(thread_id, "")
            row["event_count"] += 1
            row["events"].append({
                "event_id": event.get("id") or event.get("event_id") or "",
                "title": event.get("title") or "",
                "status": event.get("status") or "",
            })

    sources = []
    for source, payload in sorted(source_threads.items()):
        thread_rows = list(payload["threads"].values())
        sources.append({
            "source": source,
            "thread_count": len(thread_rows),
            "event_count": sum(row["event_count"] for row in thread_rows),
            "threads": sorted(thread_rows, key=lambda row: (-row["event_count"], row["thread_id"])),
        })
    return {"sources": sources}


def _thread_row() -> dict[str, Any]:
    return {"thread_id": "", "thread_title": "", "event_count": 0, "events": []}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _source(item: dict[str, Any]) -> str:
    engine = str(item.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    return str(item.get("source") or item.get("source_domain") or "unknown")
