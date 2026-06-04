"""DB-native multi-scale report synthesis.

The synthesis runtime consumes all lower-scale database state plus same-scale
fresh evidence that has already been searched and normalized into the database.
It writes the target scale's structured report, synthesized events, evidence
links, and lineage. It is deterministic and does not call search APIs or LLMs.
"""

from __future__ import annotations

import json
from typing import Any

from stratum.contracts.report_window import resolve_report_window
from stratum.db.connection import get_db
from stratum.db.persistence import upsert_report_bundle
from stratum.db.service import get_cascade_inputs
from stratum.db.synthesis.events import SynthesizedEventBuilder
from stratum.db.synthesis import payload as _payload
from stratum.db.synthesis.ranker import ThemeRanker
from stratum.db.synthesis import text as _text


SUPPORTED_TARGET_SCALES = {"weekly", "monthly", "quarterly", "yearly"}


def synthesize_cascade_report(
    domain: str,
    target_scale: str,
    target_period: str | None,
    *,
    window_start: str | None = None,
    window_end: str | None = None,
    max_threads: int = 6,
    include_same_scale_fresh: bool = True,
) -> dict[str, Any]:
    """Synthesize one higher-scale report from lower scales and fresh evidence."""
    if target_scale not in SUPPORTED_TARGET_SCALES:
        raise ValueError(f"unsupported synthesis target scale: {target_scale}")

    window = resolve_report_window(
        target_scale,
        target_period,
        start_date=window_start,
        end_date=window_end,
    )
    target_period = window.period
    inputs = get_cascade_inputs(
        domain,
        target_scale,
        target_period,
        window_start=window.start_date if window.period_kind == "custom_range" else None,
        window_end=window.end_date if window.period_kind == "custom_range" else None,
    )
    if not inputs["reports"] and not inputs["events"]:
        raise ValueError(f"no cascade inputs for {domain} {target_scale} {target_period}")
    if not include_same_scale_fresh:
        inputs["fresh_evidence"] = []

    _require_foundation(domain)
    report_id = f"report-{domain}-{target_scale}-{target_period}"
    start, end = window.start_date, window.end_date
    thread_groups = _group_events_by_thread(inputs["events"])
    top_threads = _rank_thread_groups(thread_groups, inputs.get("judgments", []))[:max_threads]
    synthesized_events = _build_synthesized_events(
        report_id,
        target_scale,
        target_period,
        end,
        top_threads,
    )
    _upsert_synthesized_events(domain, synthesized_events)

    report, sections, items, item_events, item_threads, item_articles, lineage = _build_report_payload(
        domain=domain,
        report_id=report_id,
        target_scale=target_scale,
        target_period=target_period,
        window_start=start,
        window_end=end,
        inputs=inputs,
        top_threads=top_threads,
        synthesized_events=synthesized_events,
    )
    stats = upsert_report_bundle(
        domain,
        report,
        sections=sections,
        items=items,
        item_events=item_events,
        item_threads=item_threads,
        item_articles=item_articles,
        lineage=lineage,
    )
    return {
        "domain": domain,
        "scale": target_scale,
        "period": target_period,
        "window": window.to_dict(),
        "report_id": report_id,
        "source_scale": inputs["source_scale"],
        "source_scales": inputs["source_scales"],
        "source_reports": len(inputs["reports"]),
        "source_events": len(inputs["events"]),
        "fresh_evidence": len(inputs.get("fresh_evidence", [])),
        "synthesized_events": len(synthesized_events),
        "stats": stats,
    }


def _require_foundation(domain: str) -> None:
    conn = get_db(domain)
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        required = {"reports", "report_sections", "report_items", "report_lineage"}
        if not required.issubset(tables):
            missing = ", ".join(sorted(required - tables))
            raise RuntimeError(f"DB foundation 0.1 schema is missing: {missing}")
    finally:
        conn.close()


def _group_events_by_thread(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for event in events:
        group_key = _report_topic_key(event)
        group = groups.setdefault(group_key, {"thread_id": event.get("thread_id") or group_key, "events": []})
        group["events"].append(event)
        group["thread_id"] = _representative_thread_id(group["events"], group["thread_id"])
    return groups


def _rank_thread_groups(
    groups: dict[str, dict[str, Any]],
    judgments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return ThemeRanker().rank_thread_groups(groups, judgments=judgments)


def _build_synthesized_events(
    report_id: str,
    target_scale: str,
    target_period: str,
    event_date: str,
    thread_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return SynthesizedEventBuilder().build(
        report_id=report_id,
        target_scale=target_scale,
        target_period=target_period,
        event_date=event_date,
        thread_groups=thread_groups,
    )


def _upsert_synthesized_events(domain: str, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    conn = get_db(domain)
    try:
        for event in events:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    id, thread_id, scale, date, title, article_ids, entity_ids,
                    term_ids, source_domains, confidence, briefing_id, created_at,
                    status, priority
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["thread_id"],
                    event["scale"],
                    event["date"],
                    event["title"],
                    json.dumps(event["article_ids"], ensure_ascii=False),
                    json.dumps(event["entity_ids"], ensure_ascii=False),
                    json.dumps(event["term_ids"], ensure_ascii=False),
                    json.dumps(event["source_domains"], ensure_ascii=False),
                    event["confidence"],
                    event["briefing_id"],
                    event["created_at"],
                    event["status"],
                    event["priority"],
                ),
            )
            if event["scale"] == "weekly":
                conn.execute(
                    """
                    UPDATE threads
                       SET last_event_date = MAX(COALESCE(last_event_date, ''), ?),
                           event_count_weekly = event_count_weekly + 1
                     WHERE id = ?
                    """,
                    (event["date"], event["thread_id"]),
                )
            else:
                conn.execute(
                    """
                    UPDATE threads
                       SET last_event_date = MAX(COALESCE(last_event_date, ''), ?)
                     WHERE id = ?
                    """,
                    (event["date"], event["thread_id"]),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _build_report_payload(
    *,
    domain: str,
    report_id: str,
    target_scale: str,
    target_period: str,
    window_start: str,
    window_end: str,
    inputs: dict[str, Any],
    top_threads: list[dict[str, Any]],
    synthesized_events: list[dict[str, Any]],
) -> tuple:
    return _payload.build_report_payload(
        domain=domain,
        report_id=report_id,
        target_scale=target_scale,
        target_period=target_period,
        window_start=window_start,
        window_end=window_end,
        inputs=inputs,
        top_threads=top_threads,
        synthesized_events=synthesized_events,
    )


def _synthesis_title(target_scale: str, events: list[dict[str, Any]]) -> str:
    return SynthesizedEventBuilder().synthesis_title(target_scale, events)


def _theme_body(
    target_scale: str,
    source_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    return _text._theme_body(target_scale, source_scale, events, fresh_evidence)


def _weekly_theme_body(
    target_scale: str,
    source_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    return _text._weekly_theme_body(target_scale, source_scale, events, fresh_evidence)


def _trend_body(
    target_scale: str,
    source_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    return _text._trend_body(target_scale, source_scale, events, fresh_evidence)


def _theme_judgment(theme: str, signal_count: int, fresh_count: int) -> str:
    return _text._theme_judgment(theme, signal_count, fresh_count)


def _theme_synthesis(theme: str, has_fresh: bool) -> str:
    return _text._theme_synthesis(theme, has_fresh)


def _executive_implications(theme: str) -> list[str]:
    return _text._executive_implications(theme)


def _confidence_delta_text(has_fresh: bool) -> str:
    return _text._confidence_delta_text(has_fresh)


def _theme_watch_points(theme: str) -> list[str]:
    return _text._theme_watch_points(theme)


def _fresh_evidence_body(target_scale: str, articles: list[dict[str, Any]]) -> str:
    return _text._fresh_evidence_body(target_scale, articles)


def _fresh_evidence_title(target_scale: str, articles: list[dict[str, Any]]) -> str:
    return _text._fresh_evidence_title(target_scale, articles)


def _judgment_body(judgments: list[dict[str, Any]], pending: list[dict[str, Any]]) -> str:
    return _text._judgment_body(judgments, pending)


def _unique_judgments(judgments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _text._unique_judgments(judgments)


def _section_title(scale: str) -> str:
    return _text._section_title(scale)


def _section_titles(scale: str) -> dict[str, str]:
    return _text._section_titles(scale)


def _summary_title(scale: str) -> str:
    return _text._summary_title(scale)


def _summary_body(
    scale: str,
    window_start: str,
    window_end: str,
    inputs: dict[str, Any],
    top_threads: list[dict[str, Any]],
) -> str:
    return _text._summary_body(scale, window_start, window_end, inputs, top_threads)


def _executive_summary_conclusions(top_threads: list[dict[str, Any]], fresh_count: int) -> list[str]:
    return _text._executive_summary_conclusions(top_threads, fresh_count)


def _thread_theme(thread_id: str, events: list[dict[str, Any]]) -> str:
    return _text._thread_theme(thread_id, events)


def _scale_label(scale: str) -> str:
    return _text._scale_label(scale)


def _article_titles(articles: list[dict[str, Any]], theme: str | None = None) -> list[str]:
    return _text._article_titles(articles, theme)


def _article_display_title(article: dict[str, Any], theme: str | None = None) -> str:
    return _text._article_display_title(article, theme)


def _is_chinese_display_text(text: str) -> bool:
    return _text._is_chinese_display_text(text)


def _has_japanese_or_korean(text: str) -> bool:
    return _text._has_japanese_or_korean(text)


def _article_focus_terms(article: dict[str, Any]) -> str:
    return _text._article_focus_terms(article)


def _numbered_lines(values: list[str]) -> str:
    return _text._numbered_lines(values)


def _display_hypothesis(value: str) -> str:
    return _text._display_hypothesis(value)


def _event_points(events: list[dict[str, Any]]) -> list[str]:
    return _text._event_points(events)


def _lead_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    return SynthesizedEventBuilder().lead_event(events)


def _lead_event_for_theme(theme: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return SynthesizedEventBuilder().lead_event_for_theme(theme, events)


def _event_sort_key(event: dict[str, Any]) -> tuple:
    return SynthesizedEventBuilder().event_sort_key(event)


def _title_language_penalty(title: str) -> int:
    return SynthesizedEventBuilder().title_language_penalty(title)


def _normalize_title_key(title: str) -> str:
    return _text._normalize_title_key(title)


def _report_topic_key(event: dict[str, Any]) -> str:
    return SynthesizedEventBuilder().report_topic_key(event)


def _representative_thread_id(events: list[dict[str, Any]], fallback: str) -> str:
    lead = _lead_event(events)
    return lead.get("thread_id") or fallback


def _period_label(scale: str) -> str:
    return _text._period_label(scale)


def _scale_adjective(scale: str) -> str:
    return _text._scale_adjective(scale)


def _fresh_reference_label(scale: str) -> str:
    return _text._fresh_reference_label(scale)


def _lineage_body(inputs: dict[str, Any], source_report_ids: list[str]) -> str:
    return _text._lineage_body(inputs, source_report_ids)


def _signal_noise_body(top_threads: list[dict[str, Any]]) -> str:
    return _text._signal_noise_body(top_threads)


def _fresh_coverage_title(fresh_evidence: list[dict[str, Any]]) -> str:
    return _text._fresh_coverage_title(fresh_evidence)


def _fresh_coverage_body(fresh_evidence: list[dict[str, Any]]) -> str:
    return _text._fresh_coverage_body(fresh_evidence)


def _watchlist_body(top_threads: list[dict[str, Any]], fresh_evidence: list[dict[str, Any]]) -> str:
    return _text._watchlist_body(top_threads, fresh_evidence)


def _matching_fresh_evidence(events: list[dict[str, Any]], fresh_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _text._matching_fresh_evidence(events, fresh_evidence)


def _integration_decision_text(
    target_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    return _text._integration_decision_text(target_scale, events, fresh_evidence)


def _unique_flatten(events: list[dict[str, Any]], field: str) -> list[str]:
    return _text._unique_flatten(events, field)


def _json_list(value: Any) -> list[Any]:
    return _text._json_list(value)


def _lowest_confidence(events: list[dict[str, Any]]) -> str:
    return SynthesizedEventBuilder().lowest_confidence(events)


def _slug(value: str) -> str:
    return SynthesizedEventBuilder().slug(value)
