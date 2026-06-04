"""Database consumption and management service.

This module is the semantic read surface for downstream consumers. It is
additive to the current baseline: no pipeline code depends on it yet, and every
future-table read degrades to an empty structure when the table does not exist.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from stratum.contracts.report_window import period_window, resolve_report_window
from stratum.db.connection import get_db
from stratum.db.judgment_lifecycle import JudgmentLifecyclePolicy
from stratum.db.read_model import (
    columns as _columns,
    event_row_to_dict as _event_row_to_dict,
    get_fresh_evidence as _get_fresh_evidence,
    get_report as _get_report,
    get_report_items as _get_report_items,
    get_report_lineage as _get_report_lineage,
    get_report_sections as _get_report_sections,
    get_reports_for_window as _get_reports_for_window,
    json_fields as _json_fields,
    json_list as _json_list,
    table_exists as _table_exists,
)
from stratum.db.semantic_reads import (
    EvidenceDetailReadModel,
    JudgmentStatusReadModel,
    TrackingReadModel,
    TrendReadModel,
)
from stratum.sourcing.discovery import normalize_include_domains


SCALE_ORDER = ("daily", "weekly", "monthly", "quarterly", "yearly")
_JUDGMENT_LIFECYCLE = JudgmentLifecyclePolicy()
_TREND_READ_MODEL = TrendReadModel()
_JUDGMENT_STATUS_READ_MODEL = JudgmentStatusReadModel()
_EVIDENCE_DETAIL_READ_MODEL = EvidenceDetailReadModel()
_TRACKING_READ_MODEL = TrackingReadModel()


def get_report_context(
    domain: str,
    scale: str,
    period: str,
    *,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    """Return the structured context for one report period.

    Current unmigrated databases may not have report tables yet. In that case this
    returns report=None and still supplies the event-store context for the
    requested scale/period.
    """
    window = resolve_report_window(scale, period, start_date=window_start, end_date=window_end)
    start_period, end_period = window.start_date, window.end_date
    source_briefing = f"{scale}-{period}"

    conn = get_db(domain)
    try:
        report = _get_report(conn, domain, scale, period)
        report_id = report.get("id") if report else None
        sections = _get_report_sections(conn, report_id)
        items = _get_report_items(conn, report_id)

        return {
            "domain": domain,
            "scale": scale,
            "period": window.period,
            "window": {"start": start_period, "end": end_period},
            "report_window": window.to_dict(),
            "report": report,
            "sections": sections,
            "items": items,
            "events": _get_events(conn, scale=scale, start=start_period, end=end_period),
            "threads": _get_threads_for_window(conn, start_period, end_period),
            "judgments": _get_judgments(conn, scale=scale, source_briefing=source_briefing),
            "causal_edges": _get_causal_edges(conn, scale=scale, source_briefing=source_briefing),
            "entity_snapshots": _get_entity_snapshots(conn, scale=scale, start=start_period, end=end_period),
        }
    finally:
        conn.close()


def get_story_context_records(domain: str) -> dict[str, list[dict[str, Any]]]:
    """Return normalized event-thread records for daily story context assembly."""
    conn = get_db(domain)
    try:
        return {
            "events": _get_events(conn),
            "causal_edges": _get_causal_edges(conn),
            "judgments": _get_judgments(conn),
        }
    finally:
        conn.close()


def get_thread_keyword_events(domain: str) -> list[dict[str, Any]]:
    """Return active event rows used to export thread keyword feedback."""
    conn = get_db(domain)
    try:
        if not _table_exists(conn, "events"):
            return []
        cols = _columns(conn, "events")
        required = {"id", "thread_id", "title", "entity_ids", "status"}
        if not required.issubset(cols):
            return []
        rows = conn.execute(
            """
            SELECT id, thread_id, title, entity_ids, status
              FROM events
             WHERE status IN ('active', 'pending', 'cooling', 'emerging')
            """
        ).fetchall()
        return [_json_fields(dict(row), ("entity_ids",)) for row in rows]
    finally:
        conn.close()


def load_active_search_queries_from_path(db_path: str) -> list[dict[str, Any]]:
    """Load active daily Search queries from an explicit SQLite database path."""
    intents = ["detection", "verification"]
    thread_statuses = ["emerging", "active", "cooling"]
    intent_placeholders = ",".join(["?"] * len(intents))
    status_placeholders = ",".join(["?"] * len(thread_statuses))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        query_columns = {row["name"] for row in conn.execute("PRAGMA table_info(queries)").fetchall()}
        dimension_expr = "q.dimension" if "dimension" in query_columns else "'db'"
        include_domains_expr = "q.include_domains" if "include_domains" in query_columns else "NULL"
        rows = conn.execute(
            f"""
            SELECT q.id, q.text, q.locale, q.intent,
                   {dimension_expr} AS dimension,
                   {include_domains_expr} AS include_domains
              FROM queries q
              LEFT JOIN threads t ON q.thread_id = t.id
             WHERE q.status = 'active'
               AND (q.thread_id IS NULL OR t.status IN ({status_placeholders}))
               AND q.intent IN ({intent_placeholders})
             ORDER BY q.intent, q.locale
            """,
            thread_statuses + intents,
        ).fetchall()
    finally:
        conn.close()

    queries = []
    for row in rows:
        query = {
            "id": row["id"],
            "text": row["text"],
            "locale": row["locale"] or "en",
            "intent": row["intent"] or "detection",
            "dimension": row["dimension"] or "general",
        }
        include_domains = _parse_include_domains(row["include_domains"])
        if include_domains:
            query["include_domains"] = include_domains
        queries.append(query)
    return queries


def load_latest_search_engine_health_from_path(db_path: str) -> dict[str, dict[str, Any]]:
    """Load the latest persisted Search engine health records from a DB path."""
    if not db_path:
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "search_engine_health"):
            return {}
        rows = conn.execute(
            """
            SELECT seh.*
              FROM search_engine_health seh
              JOIN (
                    SELECT engine, MAX(run_date) AS run_date
                      FROM search_engine_health
                     GROUP BY engine
                   ) latest
                ON latest.engine = seh.engine
               AND latest.run_date = seh.run_date
             ORDER BY seh.engine
            """
        ).fetchall()
        return {
            row["engine"]: _search_engine_health_row_to_dict(row)
            for row in rows
        }
    finally:
        conn.close()


def get_latest_search_engine_health(domain: str) -> dict[str, dict[str, Any]]:
    """Load latest persisted Search engine health records for a domain DB."""
    conn = get_db(domain)
    try:
        if not _table_exists(conn, "search_engine_health"):
            return {}
        rows = conn.execute(
            """
            SELECT seh.*
              FROM search_engine_health seh
              JOIN (
                    SELECT engine, MAX(run_date) AS run_date
                      FROM search_engine_health
                     GROUP BY engine
                   ) latest
                ON latest.engine = seh.engine
               AND latest.run_date = seh.run_date
             ORDER BY seh.engine
            """
        ).fetchall()
        return {
            row["engine"]: _search_engine_health_row_to_dict(row)
            for row in rows
        }
    finally:
        conn.close()


def get_cascade_inputs(
    domain: str,
    target_scale: str,
    target_period: str | None = None,
    *,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    """Assemble lower-scale database state for a higher-scale report."""
    source_scale = lower_scale(target_scale)
    source_scales = lower_scales(target_scale)
    window = resolve_report_window(
        target_scale,
        target_period,
        start_date=window_start,
        end_date=window_end,
    )
    target_period = window.period
    start_period, end_period = window.start_date, window.end_date

    conn = get_db(domain)
    try:
        inputs_by_scale = {}
        for scale in source_scales:
            inputs_by_scale[scale] = {
                "reports": _get_reports_for_window(conn, domain, scale, start_period, end_period),
                "events": _get_events(conn, scale=scale, start=start_period, end=end_period),
                "judgments": _get_judgments(conn, scale=scale, start=start_period, end=end_period),
                "causal_edges": _get_causal_edges(conn, scale=scale, start=start_period, end=end_period),
                "entity_snapshots": _get_entity_snapshots(conn, scale=scale, start=start_period, end=end_period),
                "due_judgments": _get_due_judgments(conn, scale=scale, end_period=end_period),
            }
        reports = [report for data in inputs_by_scale.values() for report in data["reports"]]
        events = [event for data in inputs_by_scale.values() for event in data["events"]]
        judgments = [judgment for data in inputs_by_scale.values() for judgment in data["judgments"]]
        causal_edges = [edge for data in inputs_by_scale.values() for edge in data["causal_edges"]]
        entity_snapshots = [snapshot for data in inputs_by_scale.values() for snapshot in data["entity_snapshots"]]
        due_judgments = [judgment for data in inputs_by_scale.values() for judgment in data["due_judgments"]]
        return {
            "domain": domain,
            "target_scale": target_scale,
            "target_period": target_period,
            "source_scale": source_scale,
            "source_scales": source_scales,
            "window": {"start": start_period, "end": end_period},
            "report_window": window.to_dict(),
            "reports": reports,
            "direct_reports": inputs_by_scale.get(source_scale, {}).get("reports", []),
            "direct_events": inputs_by_scale.get(source_scale, {}).get("events", []),
            "inputs_by_scale": inputs_by_scale,
            "events": events,
            "threads": _get_threads_for_window(conn, start_period, end_period),
            "judgments": judgments,
            "causal_edges": causal_edges,
            "entity_snapshots": entity_snapshots,
            "due_judgments": due_judgments,
            "fresh_evidence": _get_fresh_evidence(
                conn,
                domain,
                target_scale,
                target_period,
                start=start_period,
                end=end_period,
            ),
        }
    finally:
        conn.close()


def get_thread_timeline(
    domain: str,
    thread_id: str,
    start_period: str | None = None,
    end_period: str | None = None,
    scale: str | None = None,
) -> list[dict[str, Any]]:
    """Track one story/thread over time."""
    conn = get_db(domain)
    try:
        clauses = ["thread_id = ?"]
        params: list[Any] = [thread_id]
        if start_period:
            clauses.append("date >= ?")
            params.append(start_period)
        if end_period:
            clauses.append("date <= ?")
            params.append(end_period)
        if scale:
            clauses.append("scale = ?")
            params.append(scale)
        rows = conn.execute(
            f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY date ASC, priority ASC",
            params,
        ).fetchall()
        return [_event_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_entity_timeline(
    domain: str,
    entity_id: str,
    scale: str | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict[str, Any]:
    """Track one company/entity through snapshots and events."""
    conn = get_db(domain)
    try:
        snapshot_clauses = ["entity_id = ?"]
        snapshot_params: list[Any] = [entity_id]
        if scale:
            snapshot_clauses.append("scale = ?")
            snapshot_params.append(scale)
        if start_period:
            snapshot_clauses.append("period >= ?")
            snapshot_params.append(start_period)
        if end_period:
            snapshot_clauses.append("period <= ?")
            snapshot_params.append(end_period)

        snapshots = [
            _json_fields(dict(row), ("key_events", "thread_ids"))
            for row in conn.execute(
                f"""
                SELECT * FROM entity_snapshots
                WHERE {' AND '.join(snapshot_clauses)}
                ORDER BY period ASC, scale ASC
                """,
                snapshot_params,
            ).fetchall()
        ]

        events = _events_for_json_member(
            conn,
            "entity_ids",
            entity_id,
            scale=scale,
            start=start_period,
            end=end_period,
            order="ASC",
        )
        return _TRACKING_READ_MODEL.entity_timeline(
            entity_id=entity_id,
            snapshots=snapshots,
            events=events,
        )
    finally:
        conn.close()


def get_technology_progress(
    domain: str,
    term_id: str,
    entity_ids: list[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    scale: str | None = "daily",
) -> dict[str, list[dict[str, Any]]]:
    """Track one technology/term across companies and periods."""
    conn = get_db(domain)
    try:
        events = _events_for_json_member(
            conn,
            "term_ids",
            term_id,
            scale=scale,
            start=start_period,
            end=end_period,
            order="ASC",
        )
        return _TRACKING_READ_MODEL.technology_progress(
            term_id=term_id,
            events=events,
            entity_ids=entity_ids,
        )
    finally:
        conn.close()


def get_due_judgments(
    domain: str,
    scale: str | None = None,
    period: str | None = None,
) -> list[dict[str, Any]]:
    """Return judgments still pending verification."""
    conn = get_db(domain)
    try:
        end_period = period_window(scale, period)[1] if scale and period else None
        return _get_due_judgments(conn, scale=scale, end_period=end_period)
    finally:
        conn.close()


def get_report_item_evidence(domain: str, report_item_id: str) -> dict[str, Any]:
    """Return evidence links for one report item.

    This is forward-compatible with the planned report/evidence schema. On a
    current unmigrated database without those tables, it returns empty evidence.
    """
    conn = get_db(domain)
    try:
        item = None
        if _table_exists(conn, "report_items"):
            row = conn.execute("SELECT * FROM report_items WHERE id = ?", (report_item_id,)).fetchone()
            item = dict(row) if row else None

        events: list[dict[str, Any]] = []
        if _table_exists(conn, "report_item_events"):
            rows = conn.execute(
                """
                SELECT e.*
                  FROM report_item_events rie
                  JOIN events e ON e.id = rie.event_id
                 WHERE rie.report_item_id = ?
                 ORDER BY e.date ASC, e.priority ASC
                """,
                (report_item_id,),
            ).fetchall()
            events = [_event_row_to_dict(row) for row in rows]

        articles: list[dict[str, Any]] = []
        if _table_exists(conn, "report_item_articles") and _table_exists(conn, "articles"):
            rows = conn.execute(
                """
                SELECT a.*
                  FROM report_item_articles ria
                  JOIN articles a ON a.id = ria.article_id
                 WHERE ria.report_item_id = ?
                 ORDER BY a.published_at ASC, a.source ASC
                """,
                (report_item_id,),
            ).fetchall()
            articles = [dict(row) for row in rows]

        return _EVIDENCE_DETAIL_READ_MODEL.report_item_evidence(
            report_item_id=report_item_id,
            item=item,
            events=events,
            articles=articles,
        )
    finally:
        conn.close()


def get_trend_summary(
    domain: str,
    scale: str,
    start_period: str,
    end_period: str,
) -> dict[str, Any]:
    """Summarize trend signals from events, threads, entities, and judgments."""
    conn = get_db(domain)
    try:
        events = _get_events(conn, scale=scale, start=start_period, end=end_period)
        judgments = _get_judgments(conn, scale=scale, start=start_period, end=end_period)
        return _TREND_READ_MODEL.trend_summary(
            domain=domain,
            scale=scale,
            start_period=start_period,
            end_period=end_period,
            events=events,
            judgments=judgments,
        )
    finally:
        conn.close()


def get_judgment_status(
    domain: str,
    scale: str | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict[str, Any]:
    """Group judgments by verification result."""
    conn = get_db(domain)
    try:
        judgments = _get_judgments(conn, scale=scale, start=start_period, end=end_period)
        return _JUDGMENT_STATUS_READ_MODEL.status(
            domain=domain,
            scale=scale,
            start_period=start_period,
            end_period=end_period,
            judgments=judgments,
        )
    finally:
        conn.close()


def get_key_events(
    domain: str,
    scale: str,
    start_period: str,
    end_period: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return priority-ranked key events in a period."""
    conn = get_db(domain)
    try:
        events = _get_events(conn, scale=scale, start=start_period, end=end_period)
        return _TREND_READ_MODEL.key_events(events, limit=limit)
    finally:
        conn.close()


def get_key_timeline(
    domain: str,
    scale: str,
    start_period: str,
    end_period: str,
    *,
    limit_per_period: int = 5,
) -> list[dict[str, Any]]:
    """Return key dates/periods with the highest-priority events."""
    conn = get_db(domain)
    try:
        events = _get_events(conn, scale=scale, start=start_period, end=end_period)
        return _TREND_READ_MODEL.key_timeline(events, limit_per_period=limit_per_period)
    finally:
        conn.close()


def trace_report_lineage(domain: str, report_id: str) -> dict[str, Any]:
    """Trace a report back to lower-scale reports, events, threads, and articles."""
    conn = get_db(domain)
    try:
        report = None
        if _table_exists(conn, "reports"):
            row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
            report = dict(row) if row else None
        return {
            "domain": domain,
            "report_id": report_id,
            "report": report,
            "lineage": _get_report_lineage(conn, report_id),
        }
    finally:
        conn.close()


def lower_scale(scale: str) -> str:
    """Return the direct lower scale used for cascade input assembly."""
    try:
        index = SCALE_ORDER.index(scale)
    except ValueError:
        return "daily"
    if index <= 0:
        return "daily"
    return SCALE_ORDER[index - 1]


def lower_scales(scale: str) -> list[str]:
    """Return all lower scales consumed by a target scale."""
    try:
        index = SCALE_ORDER.index(scale)
    except ValueError:
        return ["daily"]
    return list(SCALE_ORDER[:index]) or ["daily"]


def _parse_include_domains(value) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        parsed = [part.strip() for part in str(value).split(",") if part.strip()]
    return normalize_include_domains(parsed)


def _search_engine_health_row_to_dict(row) -> dict[str, Any]:
    data = dict(row)
    data["errors"] = _json_list(data.get("errors"))
    for key in (
        "attempts",
        "successes",
        "no_results",
        "failures",
        "rate_limited",
        "not_configured",
        "unsupported",
    ):
        data[key] = int(data.get(key) or 0)
    for key in ("health_score", "failure_rate"):
        data[key] = float(data.get(key) or 0)
    return data


def _get_events(
    conn,
    scale: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if scale:
        clauses.append("scale = ?")
        params.append(scale)
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM events {where} ORDER BY date ASC, priority ASC",
        params,
    ).fetchall()
    return [_event_row_to_dict(row) for row in rows]


def _get_threads_for_window(conn, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM threads
         WHERE last_event_date >= ?
           AND first_event_date <= ?
         ORDER BY priority ASC, last_event_date ASC
        """,
        (start, end),
    ).fetchall()
    return [dict(row) for row in rows]


def _get_judgments(
    conn,
    scale: str | None = None,
    source_briefing: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if scale:
        clauses.append("scale = ?")
        params.append(scale)
    if source_briefing:
        clauses.append("source_briefing = ?")
        params.append(source_briefing)
    if start:
        clauses.append("created_at >= ?")
        params.append(start)
    if end:
        clauses.append("created_at <= ?")
        params.append(f"{end}T23:59:59")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM judgments {where} ORDER BY created_at ASC", params).fetchall()
    return [_json_fields(dict(row), ("target_entity_ids", "target_thread_ids")) for row in rows]


def _get_due_judgments(
    conn,
    scale: str | None = None,
    end_period: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["(result IS NULL OR result IN ('pending', 'deferred'))"]
    params: list[Any] = []
    if scale:
        clauses.append("scale = ?")
        params.append(scale)
    rows = conn.execute(
        f"SELECT * FROM judgments WHERE {' AND '.join(clauses)} ORDER BY created_at ASC",
        params,
    ).fetchall()
    judgments = [_json_fields(dict(row), ("target_entity_ids", "target_thread_ids")) for row in rows]
    if not end_period:
        return judgments
    return [
        judgment for judgment in judgments
        if _JUDGMENT_LIFECYCLE.is_due(judgment, end_period=end_period)
    ]


def _get_causal_edges(
    conn,
    scale: str | None = None,
    source_briefing: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if scale:
        clauses.append("scale = ?")
        params.append(scale)
    if source_briefing:
        clauses.append("source_briefing = ?")
        params.append(source_briefing)
    if start:
        clauses.append("created_at >= ?")
        params.append(start)
    if end:
        clauses.append("created_at <= ?")
        params.append(f"{end}T23:59:59")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM causal_edges {where} ORDER BY created_at ASC", params).fetchall()
    return [dict(row) for row in rows]


def _get_entity_snapshots(conn, scale: str | None, start: str, end: str) -> list[dict[str, Any]]:
    clauses = ["period >= ?", "period <= ?"]
    params: list[Any] = [start, end]
    if scale:
        clauses.insert(0, "scale = ?")
        params.insert(0, scale)
    rows = conn.execute(
        f"""
        SELECT * FROM entity_snapshots
        WHERE {' AND '.join(clauses)}
        ORDER BY period ASC, entity_id ASC
        """,
        params,
    ).fetchall()
    return [_json_fields(dict(row), ("key_events", "thread_ids")) for row in rows]


def _events_for_json_member(
    conn,
    column: str,
    member_id: str,
    scale: str | None = None,
    start: str | None = None,
    end: str | None = None,
    order: str = "DESC",
) -> list[dict[str, Any]]:
    events = _get_events(conn, scale=scale, start=start, end=end)
    return _TRACKING_READ_MODEL.filter_json_member(
        events,
        column=column,
        member_id=member_id,
        order=order,
    )
