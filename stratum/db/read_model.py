"""Reusable DB read-model helpers for semantic service queries."""

from __future__ import annotations

import json
from typing import Any

from stratum.contracts.report_window import period_window


def table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
    )


def columns(conn, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def json_list(value) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def json_fields(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    for field in fields:
        row[field] = json_list(row.get(field))
    return row


def json_object_fields(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    for field in fields:
        row[field] = json_object(row.get(field))
    return row


def json_object(value) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def event_row_to_dict(row) -> dict[str, Any]:
    return json_fields(dict(row), ("article_ids", "entity_ids", "term_ids", "source_domains"))


def get_report(conn, domain: str, scale: str, period: str) -> dict[str, Any] | None:
    if not table_exists(conn, "reports"):
        return None
    cols = columns(conn, "reports")
    clauses = []
    params: list[Any] = []
    if "domain" in cols:
        clauses.append("domain = ?")
        params.append(domain)
    if "scale" in cols:
        clauses.append("scale = ?")
        params.append(scale)
    if "period" in cols:
        clauses.append("period = ?")
        params.append(period)
    if not clauses:
        return None
    row = conn.execute(f"SELECT * FROM reports WHERE {' AND '.join(clauses)} LIMIT 1", params).fetchone()
    return dict(row) if row else None


def get_reports_for_window(conn, domain: str, scale: str, start: str, end: str) -> list[dict[str, Any]]:
    if not table_exists(conn, "reports"):
        return []
    cols = columns(conn, "reports")
    if not {"scale", "period"}.issubset(cols):
        return []
    clauses = ["scale = ?"]
    params: list[Any] = [scale]
    if "domain" in cols:
        clauses.insert(0, "domain = ?")
        params.insert(0, domain)
    rows = conn.execute(
        f"SELECT * FROM reports WHERE {' AND '.join(clauses)} ORDER BY period ASC",
        params,
    ).fetchall()
    reports = []
    for row in rows:
        report = dict(row)
        report_start, report_end = period_window(scale, report["period"])
        if report_start <= end and report_end >= start:
            reports.append(report)
    return reports


def get_fresh_evidence(
    conn,
    domain: str,
    scale: str,
    period: str,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    if not table_exists(conn, "articles"):
        return []
    cols = columns(conn, "articles")
    if not {"domain", "run_date", "scale"}.issubset(cols):
        return []
    clauses = ["domain = ?", "scale = ?", "(run_date = ?"]
    params: list[Any] = [domain, scale, period]
    if start and end:
        clauses[-1] += " OR (run_date >= ? AND run_date <= ?)"
        params.extend([start, end])
        if "published_at" in cols:
            clauses[-1] += " OR (published_at >= ? AND published_at <= ?)"
            params.extend([start, end])
    clauses[-1] += ")"
    rows = conn.execute(
        f"""
        SELECT * FROM articles
         WHERE {' AND '.join(clauses)}
         ORDER BY published_at ASC, source ASC, title ASC
        """,
        params,
    ).fetchall()
    return [json_fields(dict(row), ("entity_ids", "term_ids")) for row in rows]


def get_report_sections(conn, report_id: str | None) -> list[dict[str, Any]]:
    if not report_id or not table_exists(conn, "report_sections"):
        return []
    rows = conn.execute(
        "SELECT * FROM report_sections WHERE report_id = ? ORDER BY position ASC",
        (report_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_report_items(conn, report_id: str | None) -> list[dict[str, Any]]:
    if not report_id or not table_exists(conn, "report_items"):
        return []
    if table_exists(conn, "report_sections"):
        rows = conn.execute(
            """
            SELECT ri.*
              FROM report_items ri
              JOIN report_sections rs ON rs.id = ri.section_id
             WHERE ri.report_id = ?
             ORDER BY rs.position ASC, ri.position ASC
            """,
            (report_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM report_items WHERE report_id = ? ORDER BY position ASC",
            (report_id,),
        ).fetchall()
    return [json_object_fields(dict(row), ("policy_decision",)) for row in rows]


def get_report_lineage(conn, report_id: str) -> list[dict[str, Any]]:
    if not table_exists(conn, "report_lineage"):
        return []
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM report_lineage WHERE report_id = ? ORDER BY relation",
            (report_id,),
        ).fetchall()
    ]
