"""Post-validate repair helpers for briefing Markdown."""

from __future__ import annotations

import json
import re
from typing import Any

try:
    from .source_repair import (
        EDGE_SECTION_TITLE,
        NON_NEWS_ITEM_TITLES,
        _article_date_label,
        _article_source_label,
        _best_article_for_item,
        _rewrite_item,
        _source_matches_label,
        soften_overclaim_language,
    )
except ImportError:  # pragma: no cover - script/test fallback
    from source_repair import (
        EDGE_SECTION_TITLE,
        NON_NEWS_ITEM_TITLES,
        _article_date_label,
        _article_source_label,
        _best_article_for_item,
        _rewrite_item,
        _source_matches_label,
        soften_overclaim_language,
    )


def load_validate_report(path: str) -> dict:
    with open(path) as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def repair_briefing_from_validate_report(
    markdown: str,
    articles: list[dict],
    validate_report: dict,
    run_date: str,
    source_aliases: dict[str, Any],
    *,
    max_future_days: int = 1,
    stale_days: int = 2,
    max_main_rewrite_ratio: float = 0.35,
    max_main_rewrites: int = 4,
) -> tuple[str, dict]:
    """Rewrite or drop invalid items using item-level validate telemetry."""
    from stratum.stages.validate import validate_item
    from stratum.stages.validate import SourceSupportMatcher

    support_matcher = SourceSupportMatcher()
    report_details = {
        int(detail.get("item") or 0): detail
        for detail in validate_report.get("details", [])
        if detail.get("kind") == "item"
    }

    lines = markdown.splitlines()
    repaired: list[str] = []
    current_section = ""
    current_item: dict | None = None
    actions: list[dict] = []

    def flush_current() -> None:
        if not current_item:
            return
        item_index = current_item["index"]
        report_detail = report_details.get(item_index)
        if not report_detail:
            repaired.extend(current_item["lines"])
            return

        support_article = _best_support_article(
            current_item,
            articles,
            source_aliases,
            support_matcher=support_matcher,
            prefer_fresh=True,
        )
        if current_item["section"] == EDGE_SECTION_TITLE and support_article is None:
            actions.append(_action_record(current_item, "drop", report_detail["violations"], None, "unsupported_edge"))
            return
        if support_article is None:
            repaired.extend(current_item["lines"])
            actions.append(_action_record(current_item, "unchanged", report_detail["violations"], None, "no_support_article"))
            return

        rewritten_lines = _rewrite_item_from_article(current_item, support_article, run_date)
        parsed_item = {
            "title": current_item["title"],
            "body": list(current_item["body"]),
            "sources": list(current_item["sources"]),
            "date": current_item["date"],
        }
        rewritten_item = {
            "title": _extract_title(rewritten_lines),
            "body": _extract_body(rewritten_lines),
            "sources": _extract_sources(rewritten_lines),
            "date": _extract_date(rewritten_lines),
        }
        residual = validate_item(
            rewritten_item,
            articles,
            run_date,
            source_aliases,
            max_future_days=max_future_days,
            stale_days=stale_days,
        )
        if residual and current_item["section"] == EDGE_SECTION_TITLE:
            actions.append(_action_record(current_item, "drop", report_detail["violations"], support_article, "repair_residual_edge"))
            return
        if residual:
            repaired.extend(current_item["lines"])
            actions.append(_action_record(current_item, "unchanged", report_detail["violations"], support_article, "repair_residual_main"))
            return

        repaired.extend(rewritten_lines)
        reason = "rewrite_from_support_article"
        if parsed_item["title"] != rewritten_item["title"]:
            reason = "rewrite_title_and_body_from_support_article"
        actions.append(_action_record(current_item, "rewrite", report_detail["violations"], support_article, reason))

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            flush_current()
            current_item = None
            current_section = stripped.replace("## ", "", 1).strip()
            repaired.append(line)
            continue
        if stripped.startswith("### "):
            flush_current()
            title = stripped.replace("### ", "", 1).strip()
            if title in NON_NEWS_ITEM_TITLES:
                current_item = None
                repaired.append(line)
                continue
            current_item = {
                "index": sum(1 for action in actions if action.get("action") != "structural") + 1,
                "section": current_section,
                "title": title,
                "body": [],
                "sources": [],
                "date": None,
                "lines": [line],
            }
            continue
        if current_item is None:
            repaired.append(line)
            continue
        current_item["lines"].append(line)
        if stripped.startswith("*") and "·" in stripped:
            parsed = re.match(r"^\*(.+?)·(.+?)\*$", stripped)
            if parsed:
                current_item["sources"] = [source.strip() for source in parsed.group(1).split(",") if source.strip()]
                current_item["date"] = parsed.group(2).strip()
        elif stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            current_item["body"].append(stripped)

    flush_current()
    repaired_markdown = "\n".join(repaired).rstrip() + ("\n" if markdown.endswith("\n") else "")
    repaired_markdown, actions = _enforce_rewrite_budget(
        repaired_markdown,
        actions,
        max_main_rewrite_ratio=max_main_rewrite_ratio,
        max_main_rewrites=max_main_rewrites,
    )
    repair_report = {
        "status": "repaired" if any(action["action"] in {"rewrite", "drop"} for action in actions) else "no_changes",
        "input_status": validate_report.get("status"),
        "input_violations": int(validate_report.get("violations") or 0),
        "validate_rounds": 2,
        "rewritten_items": sum(1 for action in actions if action["action"] == "rewrite"),
        "dropped_items": sum(1 for action in actions if action["action"] == "drop"),
        "unchanged_invalid_items": sum(1 for action in actions if action["action"] == "unchanged"),
        "item_actions": actions,
    }
    return repaired_markdown, repair_report


def _best_support_article(
    item: dict,
    articles: list[dict],
    source_aliases: dict[str, Any],
    *,
    support_matcher,
    prefer_fresh: bool,
) -> dict | None:
    candidates: list[dict] = []
    for source in item.get("sources") or []:
        source_lower = source.lower().strip()
        source_candidates = [
            article for article in articles
            if support_matcher.article_matches_source(article, source_lower, source_aliases)
        ]
        aligned = [
            article for article in source_candidates
            if support_matcher.item_article_alignment(item, article)[0]
        ]
        candidates.extend(aligned or source_candidates)

    if not candidates:
        fallback = _best_article_for_item(item.get("title", ""), item.get("body", []), articles)
        if fallback:
            candidates = [fallback]

    if prefer_fresh:
        fresh = [article for article in candidates if not _is_background_article(article)]
        if fresh:
            candidates = fresh

    if not candidates:
        return None
    return sorted(candidates, key=_support_article_rank, reverse=True)[0]


def _support_article_rank(article: dict) -> tuple:
    source_type = str(article.get("source_type") or article.get("source_type_hint") or "media")
    source_rank = {"official": 4, "analyst": 3, "media": 2, "blog": 1}.get(source_type, 0)
    has_numeric = 1 if article.get("numeric_claims") else 0
    snippet_len = len(str(article.get("snippet") or article.get("extracted_summary") or ""))
    return (source_rank, has_numeric, snippet_len)


def _rewrite_item_from_article(item: dict, article: dict, run_date: str) -> list[str]:
    title = str(article.get("title") or item.get("title") or "").strip()
    if item.get("title", "").startswith("【边缘信号】") and not title.startswith("【边缘信号】"):
        title = f"【边缘信号】{title}"
    source = _article_source_label(article)
    source_line = f"*{source} · {_article_date_label(article, run_date)}*" if source else ""
    body = _fact_based_rewrite_paragraphs(article, item.get("section", ""))
    return _rewrite_item(title, body, source_line)


def _fact_based_rewrite_paragraphs(article: dict, section: str) -> list[str]:
    title = str(article.get("title") or "").strip()
    snippet = str(article.get("snippet") or article.get("extracted_summary") or article.get("description") or "").strip()
    snippet = re.sub(r"\s+", " ", snippet)
    snippet = snippet[:260].strip(" .。")
    if snippet:
        paragraph_1 = soften_overclaim_language(snippet)
    else:
        paragraph_1 = f"该条目围绕“{title[:80]}”汇总了当日来源可见的新增信号。"
    paragraph_2 = (
        "这个信号值得观察，但目前仍以单点证据为主，暂不替代主线供需、价格、产能或客户导入进展判断。"
        if section == EDGE_SECTION_TITLE
        else "当前证据更适合支持趋势跟踪，而不是直接下单一结论，后续仍需结合更多来源持续验证。"
    )
    return [paragraph_1, paragraph_2]


def _is_background_article(article: dict) -> bool:
    flags = set(article.get("quality_flags") or [])
    return bool(flags & {"BACKGROUND_STALE", "BACKGROUND_NO_DATE"})


def _action_record(item: dict, action: str, violations: list[str], article: dict | None, reason: str) -> dict:
    return {
        "item": item["index"],
        "section": item.get("section", ""),
        "title": item.get("title", ""),
        "action": action,
        "reason": reason,
        "violations": list(violations),
        "support_article_id": article.get("id") if article else None,
        "support_source": _article_source_label(article) if article else None,
    }


def _extract_title(lines: list[str]) -> str:
    for line in lines:
        if line.strip().startswith("### "):
            return line.strip().replace("### ", "", 1).strip()
    return ""


def _extract_body(lines: list[str]) -> list[str]:
    body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not (stripped.startswith("*") and "·" in stripped):
            body.append(stripped)
    return body


def _extract_sources(lines: list[str]) -> list[str]:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("*") and "·" in stripped:
            parsed = re.match(r"^\*(.+?)·(.+?)\*$", stripped)
            if parsed:
                return [source.strip() for source in parsed.group(1).split(",") if source.strip()]
    return []


def _extract_date(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("*") and "·" in stripped:
            parsed = re.match(r"^\*(.+?)·(.+?)\*$", stripped)
            if parsed:
                return parsed.group(2).strip()
    return None


def _enforce_rewrite_budget(
    markdown: str,
    actions: list[dict],
    *,
    max_main_rewrite_ratio: float,
    max_main_rewrites: int,
) -> tuple[str, list[dict]]:
    main_rewrites = [action for action in actions if action["action"] == "rewrite" and action["section"] != EDGE_SECTION_TITLE]
    main_items = [action for action in actions if action["section"] != EDGE_SECTION_TITLE]
    rewrite_limit = min(max_main_rewrites, max(1, int(len(main_items) * max_main_rewrite_ratio))) if main_items else max_main_rewrites
    if len(main_rewrites) <= rewrite_limit:
        return markdown, actions

    overflow_titles = {action["title"] for action in main_rewrites[rewrite_limit:]}
    kept_lines: list[str] = []
    current_item_title: str | None = None
    current_item_lines: list[str] = []

    def flush_item() -> None:
        nonlocal current_item_title, current_item_lines
        if current_item_title is None:
            return
        if current_item_title not in overflow_titles:
            kept_lines.extend(current_item_lines)
        current_item_title = None
        current_item_lines = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            flush_item()
            current_item_title = stripped.replace("### ", "", 1).strip()
            current_item_lines = [line]
            continue
        if current_item_title is None:
            kept_lines.append(line)
        else:
            current_item_lines.append(line)
    flush_item()

    updated_actions = []
    dropped_titles = overflow_titles
    for action in actions:
        if action["title"] in dropped_titles and action["action"] == "rewrite" and action["section"] != EDGE_SECTION_TITLE:
            updated = dict(action)
            updated["action"] = "drop"
            updated["reason"] = "rewrite_budget_cap"
            updated_actions.append(updated)
        else:
            updated_actions.append(action)
    repaired_markdown = "\n".join(kept_lines).rstrip() + ("\n" if markdown.endswith("\n") else "")
    return repaired_markdown, updated_actions
