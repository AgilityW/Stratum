"""Capability wrappers for DB semantic reads and diagnostics."""

from __future__ import annotations

from typing import Any

from stratum.db import service


def thread_timeline(
    *,
    domain: str,
    thread_id: str,
    start_period: str | None = None,
    end_period: str | None = None,
    scale: str | None = None,
) -> list[dict[str, Any]]:
    """Return one thread timeline through the DB service layer."""
    return service.get_thread_timeline(
        domain,
        thread_id,
        start_period=start_period,
        end_period=end_period,
        scale=scale,
    )


def thread_keywords(*, domain: str) -> list[dict[str, Any]]:
    """Return active event rows used for thread keyword feedback."""
    return service.get_thread_keyword_events(domain)


def entity_timeline(
    *,
    domain: str,
    entity_id: str,
    scale: str | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict[str, Any]:
    """Return one entity timeline through the DB service layer."""
    return service.get_entity_timeline(
        domain,
        entity_id,
        scale=scale,
        start_period=start_period,
        end_period=end_period,
    )


def technology_progress(
    *,
    domain: str,
    term_id: str,
    entity_ids: list[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    scale: str | None = "daily",
) -> dict[str, list[dict[str, Any]]]:
    """Return technology progress tracking through the DB service layer."""
    return service.get_technology_progress(
        domain,
        term_id,
        entity_ids=entity_ids,
        start_period=start_period,
        end_period=end_period,
        scale=scale,
    )


def trend_summary(
    *,
    domain: str,
    scale: str,
    start_period: str,
    end_period: str,
) -> dict[str, Any]:
    """Return scale-level trend summary through the DB service layer."""
    return service.get_trend_summary(
        domain,
        scale,
        start_period,
        end_period,
    )


def key_timeline(
    *,
    domain: str,
    scale: str,
    start_period: str,
    end_period: str,
    limit_per_period: int = 5,
) -> list[dict[str, Any]]:
    """Return key timeline milestones through the DB service layer."""
    return service.get_key_timeline(
        domain,
        scale,
        start_period,
        end_period,
        limit_per_period=limit_per_period,
    )


def key_events(
    *,
    domain: str,
    scale: str,
    start_period: str,
    end_period: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return priority-ranked key events through the DB service layer."""
    return service.get_key_events(
        domain,
        scale,
        start_period,
        end_period,
        limit=limit,
    )


def judgment_status(
    *,
    domain: str,
    scale: str | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
) -> dict[str, Any]:
    """Return grouped judgment verification status through the DB service layer."""
    return service.get_judgment_status(
        domain,
        scale=scale,
        start_period=start_period,
        end_period=end_period,
    )


def active_queries(*, db_path: str) -> list[dict[str, Any]]:
    """Load active search queries from an explicit SQLite database path."""
    return service.load_active_search_queries_from_path(db_path)


def search_health_db(*, db_path: str) -> dict[str, dict[str, Any]]:
    """Load the latest persisted search-engine health records from an explicit DB path."""
    return service.load_latest_search_engine_health_from_path(db_path)


def search_health(*, domain: str) -> dict[str, dict[str, Any]]:
    """Load the latest persisted search-engine health records for a domain DB."""
    return service.get_latest_search_engine_health(domain)


def due_judgments(
    *,
    domain: str,
    scale: str | None = None,
    period: str | None = None,
) -> list[dict[str, Any]]:
    """Return judgments still pending verification through the DB service layer."""
    return service.get_due_judgments(
        domain,
        scale=scale,
        period=period,
    )


def report_evidence(*, domain: str, report_item_id: str) -> dict[str, Any]:
    """Return report-item evidence detail through the DB service layer."""
    return service.get_report_item_evidence(domain, report_item_id)


def report_lineage(*, domain: str, report_id: str) -> dict[str, Any]:
    """Return report lineage through the DB service layer."""
    return service.trace_report_lineage(domain, report_id)


def cascade_inputs(
    *,
    domain: str,
    target_scale: str,
    target_period: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    """Return higher-scale synthesis input bundle through the DB service layer."""
    return service.get_cascade_inputs(
        domain,
        target_scale,
        target_period,
        window_start=window_start,
        window_end=window_end,
    )
