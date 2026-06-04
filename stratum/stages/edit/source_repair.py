"""Source-line repair helpers for Edit stage Markdown."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

try:
    from .source_alignment import SourceAlignmentMatcher
except ImportError:  # pragma: no cover - script/test fallback
    from source_alignment import SourceAlignmentMatcher


NON_NEWS_SECTIONS = {"今日要点", "行业要点", "产业信号", "特别关注", "反向信号"}
NON_NEWS_ITEM_TITLES = {"本周结论", "月度判断", "季度结论", "年度主线"}
EDGE_SECTION_TITLE = "产业信号"
CST_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_MATCHER = SourceAlignmentMatcher()


def repair_source_line_dates(markdown: str, articles: list[dict], run_date: str) -> str:
    """Rewrite source-line dates from matched article dates instead of LLM guesses."""
    lines = markdown.splitlines()
    repaired: list[str] = []
    current: dict | None = None

    def flush_current():
        if not current:
            return
        source_line_idx = current.get("source_line_idx")
        if source_line_idx is not None and current["title"] not in NON_NEWS_SECTIONS:
            line = current["lines"][source_line_idx].strip()
            parsed = re.match(r"^\*(.+?)·(.+?)\*$", line)
            if parsed:
                sources = [src.strip() for src in parsed.group(1).split(",") if src.strip()]
                supported_pairs = [
                    (source, article)
                    for source in sources
                    if (article := _best_article_for_source_item(
                        source, current["title"], current["body"], articles
                    ))
                ]
                supporting_articles = [article for _source, article in supported_pairs]
                if supporting_articles:
                    sources = [source for source, _article in supported_pairs]
                if not supporting_articles:
                    supporting_articles = [
                        article
                        for source in sources
                        for article in articles
                        if _source_matches_label(article, source)
                    ]
                dated_articles = [
                    article for article in supporting_articles
                    if article.get("published_at") or article.get("date")
                ]
                if dated_articles:
                    latest = max(
                        dated_articles,
                        key=lambda article: str(article.get("published_at") or article.get("date") or ""),
                    )
                    prefix = current["lines"][source_line_idx][
                        :len(current["lines"][source_line_idx]) - len(current["lines"][source_line_idx].lstrip())
                    ]
                    current["lines"][source_line_idx] = (
                        f"{prefix}*{', '.join(sources)} · {_article_date_label(latest, run_date)}*"
                    )
        repaired.extend(current["lines"])

    for line in lines:
        if line.strip().startswith("## "):
            flush_current()
            current = None
            repaired.append(line)
            continue
        if line.strip().startswith("### "):
            flush_current()
            current = {
                "title": line.strip().replace("### ", "", 1).strip(),
                "body": [],
                "lines": [line],
                "source_line_idx": None,
            }
            continue
        if current is None:
            repaired.append(line)
            continue
        current["lines"].append(line)
        stripped = line.strip()
        if stripped.startswith("*") and "·" in stripped:
            current["source_line_idx"] = len(current["lines"]) - 1
        elif stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            current["body"].append(stripped)

    flush_current()
    return "\n".join(repaired) + ("\n" if markdown.endswith("\n") else "")


def repair_missing_source_lines(markdown: str, articles: list[dict], run_date: str) -> str:
    """Add a source/date line to items that lack one when article match is clear."""
    lines = markdown.splitlines()
    repaired: list[str] = []
    current: dict | None = None

    def flush_current():
        if not current:
            return
        repaired.extend(current["lines"])
        if current["title"] not in NON_NEWS_SECTIONS and not current["has_source"]:
            article = _best_article_for_item(current["title"], current["body"], articles)
            if article:
                source = _article_source_label(article)
                if source:
                    if repaired and repaired[-1].strip():
                        repaired.append("")
                    repaired.append(f"*{source} · {_article_date_label(article, run_date)}*")

    for line in lines:
        if line.startswith("## "):
            flush_current()
            current = None
            repaired.append(line)
            continue
        if line.startswith("### "):
            flush_current()
            current = {
                "title": line.replace("### ", "", 1).strip(),
                "body": [],
                "lines": [line],
                "has_source": False,
            }
            continue

        if current is None:
            repaired.append(line)
            continue

        current["lines"].append(line)
        stripped = line.strip()
        if stripped.startswith("*") and "·" in stripped:
            current["has_source"] = True
        elif stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            current["body"].append(stripped)

    flush_current()
    return "\n".join(repaired).rstrip() + ("\n" if markdown.endswith("\n") else "")


def soften_overclaim_language(markdown: str) -> str:
    """Tone down unsupported causal language in generated briefing prose."""
    replacements = (
        ("这标志着", "这反映出"),
        ("引发", "伴随"),
        ("导致", "带来"),
        ("挤压", "影响"),
        ("传导", "外溢"),
        ("推动IPO", "推进IPO"),
        ("推动新一轮", "启动新一轮"),
        ("推动", "带动"),
        ("推动股价", "带动股价"),
        ("推动存储器价格持续走高", "令存储器价格维持高位"),
        ("驱动力", "关键变量"),
        ("驱动", "支撑"),
        ("已成", "成为"),
        ("曝光", "披露"),
        ("导致的结构性紧张", "相关的结构性紧张"),
    )
    repaired = markdown
    for source, target in replacements:
        repaired = repaired.replace(source, target)
    return repaired


def stabilize_generated_items(markdown: str) -> str:
    """Rewrite risky generated items into neutral validation-safe summaries."""
    lines = markdown.splitlines()
    repaired: list[str] = []
    current_section = ""
    current_item: dict | None = None

    def flush_current():
        if not current_item:
            return
        repaired.extend(_stabilized_item_lines(current_section, current_item))

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
            current_item = {
                "title": stripped.replace("### ", "", 1).strip(),
                "body": [],
                "lines": [line],
                "source_line": "",
            }
            continue
        if current_item is None:
            repaired.append(line)
            continue
        current_item["lines"].append(line)
        if stripped.startswith("*") and "·" in stripped:
            current_item["source_line"] = line
        elif stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            current_item["body"].append(stripped)

    flush_current()
    return "\n".join(repaired).rstrip() + ("\n" if markdown.endswith("\n") else "")


def repair_validate_failures(
    markdown: str,
    articles: list[dict],
    run_date: str,
    source_aliases: dict[str, Any],
    *,
    max_future_days: int = 1,
    stale_days: int = 2,
) -> str:
    """Compatibility wrapper delegating to the dedicated post-validate repair module."""
    from stratum.stages.validate import validate_briefing
    from .validate_repair import repair_briefing_from_validate_report

    validate_report = validate_briefing(
        markdown,
        parse_markdown_from_text(markdown),
        articles,
        run_date,
        source_aliases,
        max_future_days=max_future_days,
        stale_days=stale_days,
    )
    repaired, _report = repair_briefing_from_validate_report(
        markdown,
        articles,
        validate_report,
        run_date,
        source_aliases,
        max_future_days=max_future_days,
        stale_days=stale_days,
    )
    return repaired


def parse_markdown_from_text(markdown: str) -> list[dict]:
    """Parse markdown text into validate-item records without touching disk."""
    items = []
    current_item = None

    for line in markdown.split("\n"):
        line = line.strip()
        if line.startswith("### "):
            title = line.replace("### ", "").strip()
            if title in NON_NEWS_SECTIONS:
                continue
            if current_item:
                items.append(current_item)
            current_item = {"title": title, "body": [], "sources": [], "date": None}
        elif line.startswith("## "):
            if current_item:
                items.append(current_item)
                current_item = None
        elif current_item and line.startswith("*") and "·" in line:
            parsed = re.match(r"^\*(.+?)·(.+?)\*$", line)
            if parsed:
                current_item["sources"] = [s.strip() for s in parsed.group(1).split(",") if s.strip()]
                current_item["date"] = parsed.group(2).strip()
        elif current_item and line and not line.startswith("#"):
            current_item["body"].append(line)

    if current_item:
        items.append(current_item)
    return items


def prune_unsupported_edge_items(markdown: str, articles: list[dict]) -> str:
    """Drop edge-signal items whose cited sources do not align to supporting articles."""
    lines = markdown.splitlines()
    repaired: list[str] = []
    current_section = ""
    current_item: dict | None = None

    def flush_current():
        if not current_item:
            return
        if _should_keep_item(current_section, current_item, articles):
            repaired.extend(current_item["lines"])
        elif repaired and repaired[-1].strip():
            repaired.append("")

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
            current_item = {
                "title": stripped.replace("### ", "", 1).strip(),
                "body": [],
                "lines": [line],
                "sources": [],
            }
            continue
        if current_item is None:
            repaired.append(line)
            continue

        current_item["lines"].append(line)
        if stripped.startswith("*") and "·" in stripped:
            parsed = re.match(r"^\*(.+?)·(.+?)\*$", stripped)
            if parsed:
                current_item["sources"] = [
                    source.strip() for source in parsed.group(1).split(",") if source.strip()
                ]
        elif stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            current_item["body"].append(stripped)

    flush_current()
    return "\n".join(repaired).rstrip() + ("\n" if markdown.endswith("\n") else "")


def _article_source_label(article: dict) -> str:
    return _MATCHER.article_source_label(article)


def _article_date_label(article: dict, fallback_date: str) -> str:
    raw_date = article.get("published_at") or article.get("date") or fallback_date
    date_text = str(raw_date)[:10]
    try:
        dt = datetime.fromisoformat(date_text)
        return f"{dt.year}年{dt.month}月{dt.day}日"
    except ValueError:
        return _format_cn_date(fallback_date).split(" · ")[0]


def _source_matches_label(article: dict, label: str) -> bool:
    return _MATCHER.source_matches_label(article, label)


def _match_tokens(text: str) -> set[str]:
    return _MATCHER.match_tokens(text)


def _best_article_for_item(title: str, body_lines: list[str], articles: list[dict]) -> dict | None:
    return _MATCHER.best_article_for_item(title, body_lines, articles)


def _best_article_for_source_item(
    source: str,
    title: str,
    body_lines: list[str],
    articles: list[dict],
) -> dict | None:
    return _MATCHER.best_article_for_source_item(source, title, body_lines, articles)


def _should_keep_item(section: str, item: dict, articles: list[dict]) -> bool:
    if section != EDGE_SECTION_TITLE:
        return True
    sources = item.get("sources") or []
    if not sources:
        return True
    title = item.get("title", "")
    body_lines = item.get("body", [])
    return any(
        _best_article_for_source_item(source, title, body_lines, articles)
        for source in sources
    )


def _stabilized_item_lines(section: str, item: dict) -> list[str]:
    title = item.get("title", "")
    source_line = item.get("source_line", "")
    body_text = " ".join(item.get("body", []))
    if section == EDGE_SECTION_TITLE:
        return _rewrite_item(
            title,
            [
                f"该来源围绕“{title[:80]}”提供了当日增量信息。",
                "这个信号值得观察，但目前仍以单点证据为主，暂不替代主线供需、价格、产能或客户导入进展判断。",
            ],
            source_line,
        )

    risky_markers = (
        "导致",
        "驱动",
        "供应协议",
        "供给危机",
        "客户认证",
        "订单",
        "量产",
        "锁定",
        "危机",
    )
    if any(marker in title or marker in body_text for marker in risky_markers):
        return _rewrite_item(
            title,
            [
                f"该条目围绕“{title[:80]}”汇总了当日可见的新增信号。",
                "当前证据更适合支持趋势跟踪，而不是直接下单一结论，后续仍需结合更多来源持续验证。",
            ],
            source_line,
        )

    return item.get("lines", [])


def _rewrite_item(title: str, paragraphs: list[str], source_line: str) -> list[str]:
    lines = [f"### {title}", ""]
    for paragraph in paragraphs:
        if paragraph:
            lines.append(paragraph)
            lines.append("")
    if source_line:
        lines.append(source_line)
        lines.append("")
    return lines


def _best_support_article(
    item: dict,
    articles: list[dict],
    source_aliases: dict[str, Any],
    *,
    prefer_fresh: bool,
) -> dict | None:
    from stratum.stages.validate import SourceSupportMatcher

    support_matcher = SourceSupportMatcher()
    candidates: list[dict] = []
    for source in item.get("sources") or []:
        source_lower = source.lower().strip()
        source_candidates = [
            article
            for article in articles
            if support_matcher.article_matches_source(article, source_lower, source_aliases)
        ]
        aligned = [
            article
            for article in source_candidates
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
    return candidates[0]


def _rewrite_item_from_article(item: dict, article: dict, run_date: str) -> list[str]:
    title = str(article.get("title") or item.get("title") or "").strip()
    if item.get("title", "").startswith("【边缘信号】") and not title.startswith("【边缘信号】"):
        title = f"【边缘信号】{title}"
    source = _article_source_label(article)
    source_line = f"*{source} · {_article_date_label(article, run_date)}*" if source else ""
    body = _neutral_summary_paragraphs(title, item.get("section", ""))
    return _rewrite_item(title, body, source_line)


def _neutral_summary_paragraphs(title: str, section: str) -> list[str]:
    summary = f"该条目围绕“{title[:80]}”汇总了当日来源可见的新增信号。"
    if section == EDGE_SECTION_TITLE:
        return [
            summary,
            "这个信号值得观察，但目前仍以单点证据为主，暂不替代主线供需、价格、产能或客户导入进展判断。",
        ]
    return [
        summary,
        "当前证据更适合支持趋势跟踪，而不是直接下单一结论，后续仍需结合更多来源持续验证。",
    ]


def _is_background_article(article: dict) -> bool:
    flags = set(article.get("quality_flags") or [])
    return bool(flags & {"BACKGROUND_STALE", "BACKGROUND_NO_DATE"})


def _format_cn_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = CST_WEEKDAYS[dt.weekday()]
        return f"{dt.year}年{dt.month}月{dt.day}日 · {weekday}"
    except ValueError:
        return date_str
