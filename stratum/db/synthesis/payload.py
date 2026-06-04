"""Structured report payload assembly for DB-native synthesis.

This module turns ranked synthesis inputs into report, section, item, evidence,
and lineage records. It owns payload shape assembly, while ranking, evidence
selection, event construction, and text policy remain separate algorithm
modules.
"""

from __future__ import annotations

from typing import Any

from stratum.db.synthesis.evidence import representative_fresh_evidence as _representative_fresh_evidence
from stratum.db.synthesis.policy import evaluate_theme
from stratum.db.synthesis.text import (
    _fresh_coverage_body,
    _fresh_coverage_title,
    _fresh_evidence_body,
    _fresh_evidence_title,
    _judgment_body,
    _lineage_body,
    _matching_fresh_evidence,
    _section_titles,
    _signal_noise_body,
    _summary_body,
    _summary_title,
    _theme_body,
    _unique_flatten,
    _unique_judgments,
    _watchlist_body,
)


def build_report_payload(
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
    report = {
        "id": report_id,
        "scale": target_scale,
        "period": target_period,
        "run_date": window_end,
        "status": "ok",
        "runtime_mode": "db_native_synthesis",
    }
    section_titles = _section_titles(target_scale)
    section_order = list(section_titles)
    sections = [
        {"section_key": section_key, "title": section_titles[section_key], "position": position}
        for position, section_key in enumerate(section_order, start=1)
    ]
    items = []
    item_events = []
    item_threads = []
    item_articles = []
    lineage = []

    summary_item_id = f"{report_id}-summary"
    items.append({
        "id": summary_item_id,
        "section_key": "executive_summary" if target_scale == "weekly" else "synthesis",
        "position": 1,
        "title": _summary_title(target_scale),
        "body": _summary_body(
            target_scale,
            window_start,
            window_end,
            inputs,
            top_threads,
        ),
        "signal_type": "synthesis",
        "importance": 1,
        "confidence": "B",
    })

    event_by_thread = {event["thread_id"]: event for event in synthesized_events}
    fresh_evidence = inputs.get("fresh_evidence", [])
    for position, group in enumerate(top_threads, start=1):
        item_id = f"{report_id}-trend-{position}"
        source_events = group["events"]
        synthesized = event_by_thread[group["thread_id"]]
        relevant_fresh = _matching_fresh_evidence(source_events, fresh_evidence)
        policy_decision = evaluate_theme(
            target_scale=target_scale,
            events=source_events,
            fresh_articles=relevant_fresh,
        ).to_dict()
        items.append({
            "id": item_id,
            "section_key": "core_themes" if target_scale == "weekly" else "trend",
            "position": position,
            "title": synthesized["title"],
            "body": _theme_body(target_scale, inputs["source_scale"], source_events, relevant_fresh),
            "signal_type": "trend",
            "importance": position,
            "confidence": synthesized["confidence"],
            "policy_decision": policy_decision,
        })
        item_events.append({"report_item_id": item_id, "event_id": synthesized["id"], "link_type": "synthesized"})
        item_threads.append({"report_item_id": item_id, "thread_id": group["thread_id"]})
        for source_event in source_events:
            item_events.append({"report_item_id": item_id, "event_id": source_event["id"], "link_type": "source"})
            lineage.append({
                "source_scale": inputs["source_scale"],
                "source_period": source_event.get("date"),
                "source_event_id": source_event["id"],
                "source_thread_id": group["thread_id"],
                "relation": "synthesizes",
            })
        for article_id in _unique_flatten(source_events, "article_ids")[:6]:
            item_articles.append({"report_item_id": item_id, "article_id": article_id})
            lineage.append({"source_article_id": article_id, "relation": "uses_evidence"})
        for article in relevant_fresh[:3]:
            item_articles.append({
                "report_item_id": item_id,
                "article_id": article["id"],
                "role": "fresh_evidence",
                "source_line": article.get("title", ""),
            })

    judgments = inputs.get("judgments", [])
    reviewed_judgments = [
        judgment for judgment in judgments
        if judgment.get("result") and judgment.get("result") != "pending"
    ]
    pending = _unique_judgments(
        [judgment for judgment in inputs.get("due_judgments", []) if not judgment.get("result") or judgment.get("result") == "pending"]
    )
    if fresh_evidence and target_scale != "weekly":
        fresh_item_id = f"{report_id}-fresh-evidence"
        items.append({
            "id": fresh_item_id,
            "section_key": "fresh",
            "position": 1,
            "title": _fresh_evidence_title(target_scale, fresh_evidence),
            "body": _fresh_evidence_body(target_scale, fresh_evidence),
            "signal_type": "fresh_evidence",
            "importance": 2,
            "confidence": "B",
        })
        for article in fresh_evidence[:12]:
            item_articles.append({
                "report_item_id": fresh_item_id,
                "article_id": article["id"],
                "role": "fresh_evidence",
                "source_line": article.get("title", ""),
            })
            lineage.append({
                "source_scale": target_scale,
                "source_period": target_period,
                "source_article_id": article["id"],
                "relation": "fresh_evidence",
            })

    if target_scale == "weekly":
        fresh_coverage_item_id = f"{report_id}-fresh-coverage"
        items.append({
            "id": f"{report_id}-signal-noise",
            "section_key": "signal_noise",
            "position": 1,
            "title": "哪些升级为周度信号，哪些暂不升级",
            "body": _signal_noise_body(top_threads),
            "signal_type": "signal_noise",
            "importance": 2,
            "confidence": "B",
        })
        items.append({
            "id": fresh_coverage_item_id,
            "section_key": "fresh_coverage",
            "position": 1,
            "title": _fresh_coverage_title(fresh_evidence),
            "body": _fresh_coverage_body(fresh_evidence),
            "signal_type": "fresh_evidence_coverage",
            "importance": 2,
            "confidence": "B" if fresh_evidence else "C",
        })
        for article in _representative_fresh_evidence(fresh_evidence)[:12]:
            item_articles.append({
                "report_item_id": fresh_coverage_item_id,
                "article_id": article["id"],
                "role": "fresh_evidence",
                "source_line": article.get("title", ""),
            })
            lineage.append({
                "source_scale": target_scale,
                "source_period": target_period,
                "source_article_id": article["id"],
                "relation": "fresh_evidence",
            })
        items.append({
            "id": f"{report_id}-watchlist",
            "section_key": "watchlist",
            "position": 1,
            "title": "下周观察点",
            "body": _watchlist_body(top_threads, fresh_evidence),
            "signal_type": "watchlist",
            "importance": 1,
            "confidence": "B",
        })

    judgment_item_id = f"{report_id}-judgments"
    items.append({
        "id": judgment_item_id,
        "section_key": "judgment_tracker" if target_scale == "weekly" else "judgment",
        "position": 1,
        "title": f"复核 {len(reviewed_judgments)} 条判断，{len(pending)} 条待验证",
        "body": _judgment_body(reviewed_judgments, pending),
        "signal_type": "judgment",
        "importance": 1,
        "confidence": "B",
    })

    lineage_item_id = f"{report_id}-lineage"
    source_report_ids = [report["id"] for report in inputs.get("reports", []) if report.get("id")]
    items.append({
        "id": lineage_item_id,
        "section_key": "source_boundary" if target_scale == "weekly" else "lineage",
        "position": 1,
        "title": f"本周期参考 {len(source_report_ids)} 份下级报告",
        "body": _lineage_body(inputs, source_report_ids),
        "signal_type": "lineage",
        "importance": 1,
        "confidence": "A",
    })
    for source_report in inputs.get("reports", []):
        lineage.append({
            "source_report_id": source_report.get("id"),
            "source_scale": source_report.get("scale"),
            "source_period": source_report.get("period"),
            "relation": "consumes",
        })
    return report, sections, items, item_events, item_threads, item_articles, lineage
