"""Structured persistence helpers for reports, evidence, and lineage.

These helpers target the explicit DB foundation 0.1 schema. They are not called by
the production pipeline unless a caller opts in after migration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urlparse

from stratum.db.connection import get_db


CST = timezone(timedelta(hours=8))

FOUNDATION_TABLES = {
    "reports",
    "report_sections",
    "report_items",
    "report_item_events",
    "report_item_threads",
    "report_item_articles",
    "report_artifacts",
    "event_articles",
}

FOUNDATION_ARTICLE_COLUMNS = {
    "canonical_url",
    "source_domain",
    "run_date",
    "scale",
    "entity_ids",
    "term_ids",
    "content_hash",
    "artifact_path",
}


def foundation_schema_ready(conn) -> bool:
    """Return whether the explicit foundation persistence contract is available."""
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    if not FOUNDATION_TABLES.issubset(tables):
        return False
    article_columns = {row["name"] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
    return FOUNDATION_ARTICLE_COLUMNS.issubset(article_columns)


def _now() -> str:
    return datetime.now(CST).isoformat()


def _json(value) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _json_object(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _source_domain(url: str | None, source: str | None = None) -> str:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or (source or "")


def _content_hash(article: dict[str, Any]) -> str:
    basis = "|".join(str(article.get(key, "")) for key in ("url", "title", "published_at", "snippet"))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def upsert_articles(
    domain: str,
    articles: list[dict[str, Any]],
    run_date: str,
    artifact_path: str | None = None,
    scale: str = "daily",
) -> int:
    """Persist lightweight article evidence metadata."""
    conn = get_db(domain)
    count = 0
    try:
        for article in articles:
            article_id = str(article.get("id") or "").strip()
            if not article_id:
                continue
            url = article.get("url") or ""
            source = article.get("source") or article.get("source_name") or ""
            conn.execute(
                """
                INSERT OR REPLACE INTO articles (
                    id, title, url, canonical_url, source, source_domain,
                    published_at, locale, snippet, domain, run_date, scale, entity_ids,
                    term_ids, content_hash, artifact_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    article.get("title", ""),
                    url,
                    article.get("canonical_url") or url,
                    source,
                    article.get("source_domain") or _source_domain(url, source),
                    article.get("published_at") or article.get("date", ""),
                    article.get("locale") or article.get("language", ""),
                    article.get("snippet") or article.get("summary", ""),
                    domain,
                    run_date,
                    article.get("scale") or scale,
                    _json(article.get("entity_ids", article.get("entities", []))),
                    _json(article.get("term_ids", article.get("terms", []))),
                    article.get("content_hash") or _content_hash(article),
                    artifact_path or article.get("artifact_path", ""),
                ),
            )
            count += 1
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_report_bundle(
    domain: str,
    report: dict[str, Any],
    sections: list[dict[str, Any]] | None = None,
    items: list[dict[str, Any]] | None = None,
    item_events: list[dict[str, Any]] | None = None,
    item_threads: list[dict[str, Any]] | None = None,
    item_articles: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    lineage: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Persist one structured report plus optional links."""
    conn = get_db(domain)
    stats = {
        "reports": 0,
        "sections": 0,
        "items": 0,
        "item_events": 0,
        "item_threads": 0,
        "item_articles": 0,
        "artifacts": 0,
        "lineage": 0,
    }
    try:
        report_id = _upsert_report(conn, domain, report)
        stats["reports"] = 1
        _clear_report_children(conn, report_id)
        section_ids: dict[str, str] = {}
        for section in sections or []:
            section_id = _upsert_section(conn, report_id, section)
            section_ids[section.get("section_key", section_id)] = section_id
            stats["sections"] += 1

        for item in items or []:
            item = dict(item)
            if "section_id" not in item and item.get("section_key") in section_ids:
                item["section_id"] = section_ids[item["section_key"]]
            _upsert_item(conn, report_id, item)
            stats["items"] += 1

        for link in item_events or []:
            _insert_item_event(conn, link)
            stats["item_events"] += 1
        for link in item_threads or []:
            _insert_item_thread(conn, link)
            stats["item_threads"] += 1
        for link in item_articles or []:
            _insert_item_article(conn, link)
            stats["item_articles"] += 1
        for artifact in artifacts or []:
            _upsert_artifact(conn, report_id, artifact)
            stats["artifacts"] += 1
        for entry in lineage or []:
            _insert_lineage(conn, report_id, entry)
            stats["lineage"] += 1

        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _clear_report_children(conn, report_id: str) -> None:
    rows = conn.execute("SELECT id FROM report_items WHERE report_id = ?", (report_id,)).fetchall()
    item_ids = [row["id"] for row in rows]
    for item_id in item_ids:
        conn.execute("DELETE FROM report_item_events WHERE report_item_id = ?", (item_id,))
        conn.execute("DELETE FROM report_item_threads WHERE report_item_id = ?", (item_id,))
        conn.execute("DELETE FROM report_item_articles WHERE report_item_id = ?", (item_id,))
    conn.execute("DELETE FROM report_items WHERE report_id = ?", (report_id,))
    conn.execute("DELETE FROM report_sections WHERE report_id = ?", (report_id,))
    conn.execute("DELETE FROM report_artifacts WHERE report_id = ?", (report_id,))
    conn.execute("DELETE FROM report_lineage WHERE report_id = ?", (report_id,))


def link_event_articles(domain: str, links: list[dict[str, Any]]) -> int:
    """Persist normalized event-to-article evidence links."""
    conn = get_db(domain)
    count = 0
    try:
        for link in links:
            conn.execute(
                """
                INSERT OR REPLACE INTO event_articles
                    (event_id, article_id, role, confidence)
                VALUES (?, ?, ?, ?)
                """,
                (
                    link["event_id"],
                    link["article_id"],
                    link.get("role", "supporting"),
                    link.get("confidence", "B"),
                ),
            )
            count += 1
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _upsert_report(conn, domain: str, report: dict[str, Any]) -> str:
    report_id = report.get("id") or f"report-{domain}-{report['scale']}-{report['period']}"
    conn.execute(
        """
        INSERT OR REPLACE INTO reports (
            id, domain, scale, period, run_date, status, version, runtime_mode,
            release_commit, markdown_path, html_path, pdf_path,
            run_manifest_path, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            domain,
            report["scale"],
            report["period"],
            report.get("run_date", report["period"]),
            report.get("status", "ok"),
            report.get("version", ""),
            report.get("runtime_mode", ""),
            report.get("release_commit", ""),
            report.get("markdown_path", ""),
            report.get("html_path", ""),
            report.get("pdf_path", ""),
            report.get("run_manifest_path", ""),
            report.get("created_at", _now()),
        ),
    )
    return report_id


def _upsert_section(conn, report_id: str, section: dict[str, Any]) -> str:
    section_key = section["section_key"]
    section_id = section.get("id") or f"{report_id}-section-{section_key}"
    conn.execute(
        """
        INSERT OR REPLACE INTO report_sections
            (id, report_id, section_key, title, position)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            section_id,
            report_id,
            section_key,
            section.get("title", section_key),
            int(section.get("position", 0)),
        ),
    )
    return section_id


def _upsert_item(conn, report_id: str, item: dict[str, Any]) -> str:
    item_id = item["id"]
    columns = _columns(conn, "report_items")
    names = [
        "id",
        "report_id",
        "section_id",
        "section_key",
        "position",
        "title",
        "body",
        "signal_type",
        "importance",
        "confidence",
    ]
    values = [
        item_id,
        report_id,
        item["section_id"],
        item.get("section_key", ""),
        int(item.get("position", 0)),
        item.get("title", ""),
        item.get("body", ""),
        item.get("signal_type", ""),
        item.get("importance"),
        item.get("confidence", "B"),
    ]
    if "policy_decision" in columns:
        names.append("policy_decision")
        values.append(_json_object(item.get("policy_decision")))
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO report_items (
            {', '.join(names)}
        )
        VALUES ({placeholders})
        """,
        values,
    )
    return item_id


def _columns(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_item_event(conn, link: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO report_item_events
            (report_item_id, event_id, link_type, confidence)
        VALUES (?, ?, ?, ?)
        """,
        (
            link["report_item_id"],
            link["event_id"],
            link.get("link_type", "primary"),
            link.get("confidence", "B"),
        ),
    )


def _insert_item_thread(conn, link: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO report_item_threads
            (report_item_id, thread_id, link_type, confidence)
        VALUES (?, ?, ?, ?)
        """,
        (
            link["report_item_id"],
            link["thread_id"],
            link.get("link_type", "primary"),
            link.get("confidence", "B"),
        ),
    )


def _insert_item_article(conn, link: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO report_item_articles
            (report_item_id, article_id, role, source_line, confidence)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            link["report_item_id"],
            link["article_id"],
            link.get("role", "evidence"),
            link.get("source_line", ""),
            link.get("confidence", "B"),
        ),
    )


def _upsert_artifact(conn, report_id: str, artifact: dict[str, Any]) -> None:
    artifact_type = artifact["artifact_type"]
    artifact_id = artifact.get("id") or f"{report_id}-artifact-{artifact_type}"
    conn.execute(
        """
        INSERT OR REPLACE INTO report_artifacts
            (id, report_id, artifact_type, path, sha256, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            report_id,
            artifact_type,
            artifact["path"],
            artifact.get("sha256", ""),
            artifact.get("created_at", _now()),
        ),
    )


def _insert_lineage(conn, report_id: str, entry: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO report_lineage (
            report_id, source_report_id, source_scale, source_period,
            source_event_id, source_thread_id, source_article_id, relation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            entry.get("source_report_id"),
            entry.get("source_scale"),
            entry.get("source_period"),
            entry.get("source_event_id"),
            entry.get("source_thread_id"),
            entry.get("source_article_id"),
            entry.get("relation", "consumes"),
        ),
    )
