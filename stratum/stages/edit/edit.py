#!/usr/bin/env python3
"""edit.py — Agent Edit: LLM generates validated briefing.md from articles + clusters.

Thin orchestration layer. Prompt assembly delegated to assembler.py.
LLM call delegated to llm_client.py.

Input:  verified articles (JSONL), clusters (JSON), story context (JSON),
        domain.yaml, config.yaml, manifest + prompt fragments.
Output: briefing.md (+ optional event-threads.json for threads/causal_edges/judgments).

Usage:
    python3 edit.py --domain storage --date 2026-05-29 --timescale daily \\
        --articles articles.jsonl --clusters clusters.json \\
        --context story_context.json --config config.yaml \\
        --output briefing.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import yaml
from datetime import datetime
from urllib.parse import urlparse

# ── Internal imports ──
_EDIT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _EDIT_DIR)
from assembler import assemble, _format_cn_date
from llm_client import call_llm

CST_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
THREAD_ID_RE = re.compile(r"^et-[A-Za-z0-9][A-Za-z0-9_-]*$")
NON_NEWS_SECTIONS = {"今日要点", "关注", "反向信号"}
EDGE_SIGNAL_KEYWORDS = (
    "anthropic",
    "模型公司",
    "玻璃硬盘",
    "玻璃存储",
    "威刚",
    "创见",
    "模组",
    "董事会",
    "任命",
    "光盘",
)


def load_config_with_env(config_path: str) -> dict:
    """Load config.yaml, resolving ${VAR} and reading .env from config's directory."""
    config_dir = os.path.dirname(os.path.abspath(config_path))
    env_path = os.path.join(config_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val

    with open(config_path) as f:
        raw = f.read()
    for match in re.finditer(r'\$\{(\w+)\}', raw):
        var_name = match.group(1)
        env_val = os.environ.get(var_name, "")
        raw = raw.replace(match.group(0), env_val)
    return yaml.safe_load(raw)


def load_articles(path: str) -> list[dict]:
    """Load articles from JSONL file."""
    articles = []
    with open(path) as f:
        for line in f:
            if line.strip():
                articles.append(json.loads(line))
    return articles


def load_domain_cfg(domain_config_path: str) -> dict:
    """Load full domain.yaml."""
    with open(domain_config_path) as f:
        return yaml.safe_load(f)


def resolve_domain_title(config: dict, domain_cfg: dict, domain_id: str) -> str:
    """Resolve the briefing title from config override, domain.yaml, or fallback."""
    channels = config.get("channels", {})
    channel_title = channels.get(domain_id, {}).get("title", "") if isinstance(channels, dict) else ""
    domain_title = domain_cfg.get("domain", {}).get("title", "") if isinstance(domain_cfg, dict) else ""
    return channel_title or domain_title or f"{domain_id}早报"


def split_llm_output(response: str) -> tuple[str, dict | None]:
    """Split LLM response into briefing markdown and structured data.

    Expects: markdown\\n---DATA---\\n{json}
    Returns: (briefing_md, structured_data_or_None)
    """
    marker = "---DATA---"
    if marker in response:
        parts = response.split(marker, 1)
        briefing = parts[0].strip()
        try:
            data = json.loads(parts[1].strip())
        except json.JSONDecodeError:
            # Graceful fallback: try to extract JSON block
            match = re.search(r'\{[\s\S]*\}', parts[1])
            try:
                data = json.loads(match.group(0)) if match else None
            except json.JSONDecodeError:
                data = None
        return briefing, data
    return response.strip(), None


def strip_source_locale_tags(markdown: str) -> str:
    """Remove source-line language tags like [en] and [zh-CN] from LLM output."""
    locale_tag = r"\s*\[(?:[A-Za-z]{2,3}(?:-[A-Za-z]{2,8}){0,2})\]"

    def replace_line(match: re.Match) -> str:
        line = match.group(0)
        return re.sub(locale_tag, "", line)

    return re.sub(r"^\*[^*\n]*·[^*\n]*\*$", replace_line, markdown, flags=re.MULTILINE)


def normalize_structured_data(
    data: dict | None,
    domain_id: str = "domain",
    run_date: str = "",
) -> dict | None:
    """Normalize common LLM key drift in optional structured output."""
    if not isinstance(data, dict):
        return data
    for key in ("threads", "causal_edges", "judgments"):
        data[key] = _normalize_structured_list(data.get(key))
    thread_id_map: dict[str, str] = {}
    for index, thread in enumerate(data.get("threads", []), start=1):
        if not isinstance(thread, dict):
            continue
        original_id = str(thread.get("thread_id") or thread.get("id") or "").strip()
        thread_id = original_id
        if not _is_valid_thread_id(thread_id):
            thread_id = _synthetic_thread_id(domain_id, run_date, thread, index)
        if original_id and original_id != thread_id:
            thread_id_map[original_id] = thread_id
        thread["thread_id"] = thread_id
        thread["id"] = thread_id
    for edge in data.get("causal_edges", []):
        if not isinstance(edge, dict):
            continue
        for key in ("cause_thread_id", "effect_thread_id"):
            value = str(edge.get(key) or "").strip()
            if value in thread_id_map:
                edge[key] = thread_id_map[value]
    for judgment in data.get("judgments", []):
        if isinstance(judgment, dict) and "hypothesis" not in judgment and "mechanism" in judgment:
            judgment["hypothesis"] = judgment.pop("mechanism")
        if isinstance(judgment, dict) and isinstance(judgment.get("target_thread_ids"), list):
            judgment["target_thread_ids"] = [
                thread_id_map.get(str(thread_id), thread_id)
                for thread_id in judgment.get("target_thread_ids", [])
            ]
    return data


def _normalize_structured_list(value) -> list:
    """Return a list for structured-output array fields."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _is_valid_thread_id(thread_id: str) -> bool:
    return bool(thread_id and THREAD_ID_RE.match(thread_id))


def _synthetic_thread_id(domain_id: str, run_date: str, thread: dict, index: int) -> str:
    """Build a deterministic id for new LLM-created threads."""
    title = str(thread.get("title") or thread.get("label") or thread.get("canonical_question") or "")
    seed = f"{domain_id}|{run_date}|{index}|{title}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    date_part = re.sub(r"[^0-9]", "", run_date) or "undated"
    domain_part = re.sub(r"[^a-z0-9_-]+", "-", domain_id.lower()).strip("-") or "domain"
    return f"et-{domain_part}-{date_part}-{digest}"


def structured_event_counts(data: dict | None) -> dict[str, int]:
    """Count structured event-thread surfaces that should be persisted."""
    if not isinstance(data, dict):
        return {"threads": 0, "causal_edges": 0, "judgments": 0}
    return {
        "threads": len(data.get("threads") if isinstance(data.get("threads"), list) else []),
        "causal_edges": len(data.get("causal_edges") if isinstance(data.get("causal_edges"), list) else []),
        "judgments": len(data.get("judgments") if isinstance(data.get("judgments"), list) else []),
    }


def should_write_event_threads(data: dict | None) -> bool:
    """Return True when structured output carries any event-thread state."""
    return any(structured_event_counts(data).values())


def markdown_news_titles(markdown: str) -> list[str]:
    """Return markdown item titles, excluding structural sections."""
    titles = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("### "):
            continue
        title = stripped.replace("### ", "", 1).strip()
        if title not in NON_NEWS_SECTIONS:
            titles.append(title)
    return titles


def normalize_edge_signal_headings(markdown: str) -> str:
    """Prefix weak-signal item headings so they stay visually separated."""
    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("### "):
            lines.append(line)
            continue
        title = stripped.replace("### ", "", 1).strip()
        if title in NON_NEWS_SECTIONS or title.startswith("【边缘信号】"):
            lines.append(line)
            continue
        title_lower = title.lower()
        if any(keyword.lower() in title_lower for keyword in EDGE_SIGNAL_KEYWORDS):
            prefix = line[:len(line) - len(line.lstrip())]
            lines.append(f"{prefix}### 【边缘信号】{title}")
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")


def item_count_within_budget(markdown: str, output_cfg: dict) -> tuple[bool, str]:
    """Check generated news item count against prompt budget."""
    budget = output_cfg.get("_budget", {}) if isinstance(output_cfg, dict) else {}
    min_items = int(budget.get("min_items", 0) or 0)
    max_items = int(budget.get("max_items", 0) or 0)
    main_min_items = int(budget.get("main_min_items", 0) or 0)
    main_max_items = int(budget.get("main_max_items", 0) or 0)
    edge_min_items = int(budget.get("edge_min_items", 0) or 0)
    edge_max_items = int(budget.get("edge_max_items", 0) or 0)
    titles = markdown_news_titles(markdown)
    count = len(titles)
    edge_count = sum(1 for title in titles if title.startswith("【边缘信号】"))
    main_count = count - edge_count
    if min_items and count < min_items:
        return False, f"generated {count} news items; total minimum is {min_items}"
    if max_items and count > max_items:
        return False, f"generated {count} news items; total maximum is {max_items}"
    if main_min_items and main_count < main_min_items:
        return False, f"generated {main_count} main news items; main minimum is {main_min_items}"
    if main_max_items and main_count > main_max_items:
        return False, f"generated {main_count} main news items; main maximum is {main_max_items}"
    if edge_min_items and edge_count < edge_min_items:
        return False, f"generated {edge_count} edge-signal items; edge minimum is {edge_min_items}"
    if edge_max_items and edge_count > edge_max_items:
        return False, f"generated {edge_count} edge-signal items; edge maximum is {edge_max_items}"
    return True, f"generated {count} news items ({main_count} main, {edge_count} edge-signal)"


def _article_source_label(article: dict) -> str:
    """Best display label for a source line."""
    source = article.get("source") or article.get("source_domain") or ""
    if source:
        return str(source).strip()
    url = article.get("url", "")
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    return host


def _article_date_label(article: dict, fallback_date: str) -> str:
    """Return Chinese date label for source lines."""
    raw_date = article.get("published_at") or article.get("date") or fallback_date
    date_text = str(raw_date)[:10]
    try:
        dt = datetime.fromisoformat(date_text)
        return f"{dt.year}年{dt.month}月{dt.day}日"
    except ValueError:
        return _format_cn_date(fallback_date).split(" · ")[0]


def _source_matches_label(article: dict, label: str) -> bool:
    article_source = _article_source_label(article).lower()
    source_label = label.lower().strip()
    if article_source == source_label:
        return True
    url = str(article.get("url") or "").lower()
    return bool(source_label and source_label in url)


def _match_tokens(text: str) -> set[str]:
    """Extract rough multilingual tokens for deterministic item/article matching."""
    tokens = set()
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]*|[\u4e00-\u9fff]{2,}", text.lower()):
        if len(token) >= 2:
            tokens.add(token)
    return tokens


def _best_article_for_item(title: str, body_lines: list[str], articles: list[dict]) -> dict | None:
    """Find the best article backing a markdown item by token overlap."""
    item_tokens = _match_tokens(f"{title} {' '.join(body_lines)}")
    if not item_tokens:
        return None

    best_article = None
    best_score = 0.0
    for article in articles:
        article_tokens = _match_tokens(
            f"{article.get('title', '')} {article.get('snippet', '')}"
        )
        if not article_tokens:
            continue
        overlap = len(item_tokens & article_tokens)
        score = overlap / max(1, min(len(item_tokens), len(article_tokens)))
        if score > best_score:
            best_score = score
            best_article = article

    return best_article if best_score >= 0.35 else None


def _best_article_for_source_item(
    source: str,
    title: str,
    body_lines: list[str],
    articles: list[dict],
) -> dict | None:
    """Find the best article from a cited source backing a markdown item."""
    source_articles = [article for article in articles if _source_matches_label(article, source)]
    return _best_article_for_item(title, body_lines, source_articles)


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
                supporting_articles = [
                    article
                    for source in sources
                    if (article := _best_article_for_source_item(
                        source, current["title"], current["body"], articles
                    ))
                ]
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


def prepare_llm_response(response: str, articles: list[dict], run_date: str, domain_id: str) -> tuple[str, dict | None]:
    """Split, repair, and normalize one LLM response."""
    briefing, structured_data = split_llm_output(response)
    briefing = strip_source_locale_tags(briefing)
    briefing = repair_missing_source_lines(briefing, articles, run_date)
    briefing = normalize_edge_signal_headings(briefing)
    briefing = repair_source_line_dates(briefing, articles, run_date)
    structured_data = normalize_structured_data(structured_data, domain_id, run_date)
    return briefing, structured_data


def main():
    parser = argparse.ArgumentParser(description="LLM-driven briefing generation")
    parser.add_argument("--domain", "-d", required=True, help="Domain ID (e.g. 'storage')")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--timescale", "-t", default="daily",
                        choices=["daily", "weekly", "monthly", "quarterly", "yearly"],
                        help="Timescale (default: daily)")
    parser.add_argument("--articles", required=True, help="Path to articles.jsonl")
    parser.add_argument("--clusters", required=True, help="Path to clusters.json")
    parser.add_argument("--context", required=True, help="Path to story_context.json")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--output", "-o", required=True, help="Output briefing.md path")
    args = parser.parse_args()

    # ── Load config and resolve API keys ──
    config = load_config_with_env(args.config)
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("api_key"):
        print("❌ No LLM API key configured. Add 'llm.api_key' to config.yaml")
        sys.exit(1)

    # ── Load data ──
    articles = load_articles(args.articles)
    with open(args.clusters) as f:
        clusters = json.load(f)
    context = {}
    if os.path.exists(args.context):
        with open(args.context) as f:
            context = json.load(f)

    # ── Load domain config ──
    # Derive domain.yaml path from config or convention
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    domain_config_path = os.path.join(project_root, "domains", args.domain, "domain.yaml")
    domain_cfg = load_domain_cfg(domain_config_path)
    title = resolve_domain_title(config, domain_cfg, args.domain)

    # ── Assemble prompt via assembler ──
    prompts_dir = os.path.join(_EDIT_DIR, "prompts")
    manifest_path = os.path.join(prompts_dir, "manifest.yaml")

    print(f"\n📝 Assembling prompt (timescale={args.timescale})...", file=sys.stderr)
    system_prompt, user_prompt, output_cfg = assemble(
        manifest_path=manifest_path,
        prompts_dir=prompts_dir,
        timescale=args.timescale,
        domain_cfg=domain_cfg,
        domain_id=args.domain,
        run_date=args.date,
        title=title,
        articles=articles,
        clusters=clusters,
        context=context,
    )

    print(f"   System prompt: {len(system_prompt)} chars", file=sys.stderr)
    print(f"   User prompt:   {len(user_prompt)} chars", file=sys.stderr)
    print(f"   Model: {llm_cfg.get('model', 'deepseek-v4-pro')}", file=sys.stderr)
    print(f"   Title: {title or '(from domain)'}", file=sys.stderr)

    # ── Call LLM ──
    print(f"   Calling LLM...", file=sys.stderr)
    try:
        response = call_llm(system_prompt, user_prompt, llm_cfg)
    except Exception as e:
        print(f"❌ LLM call failed: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Split output ──
    briefing, structured_data = prepare_llm_response(response, articles, args.date, args.domain)
    in_budget, budget_detail = item_count_within_budget(briefing, output_cfg)
    if not in_budget:
        print(f"⚠️  LLM output outside item budget: {budget_detail}; retrying once", file=sys.stderr)
        retry_prompt = (
            user_prompt
            + "\n\n## 强制修正\n"
            + f"上一版不符合条数要求：{budget_detail}。\n"
            + "请重写完整简报，必须严格满足总条数、主线新闻条数、边缘信号条数要求；"
            + "保留 `---DATA---` 结构化 JSON；弱相关条目必须使用 `【边缘信号】` 前缀。\n"
            + "上一版标题如下：\n"
            + "\n".join(f"- {title}" for title in markdown_news_titles(briefing))
        )
        try:
            response = call_llm(system_prompt, retry_prompt, llm_cfg)
            briefing, structured_data = prepare_llm_response(response, articles, args.date, args.domain)
            in_budget, budget_detail = item_count_within_budget(briefing, output_cfg)
        except Exception as e:
            print(f"❌ LLM retry failed: {e}", file=sys.stderr)
            sys.exit(1)
    if not in_budget:
        print(f"❌ LLM output still outside item budget after retry: {budget_detail}", file=sys.stderr)
        sys.exit(1)
    print(f"   Item budget: {budget_detail}", file=sys.stderr)

    # ── Apply header ──
    if title:
        cn_date = _format_cn_date(args.date)
        header = f"# {title}\n## {cn_date}\n\n"
        if not briefing.startswith("# "):
            briefing = header + briefing

    # ── Write briefing.md ──
    output_dir = os.path.dirname(args.output) or "."
    os.makedirs(output_dir, exist_ok=True)
    with open(args.output, "w") as f:
        f.write(briefing)
    print(f"✅ Briefing written: {args.output} ({len(briefing)} chars)", file=sys.stderr)

    # ── Write event-threads.json (if structured output) ──
    if should_write_event_threads(structured_data):
        event_threads_path = os.path.join(output_dir, "event-threads.json")
        with open(event_threads_path, "w") as f:
            json.dump(structured_data, f, ensure_ascii=False, indent=2)
        counts = structured_event_counts(structured_data)
        print(f"✅ Event threads written: {event_threads_path} "
              f"({counts['threads']} threads, {counts['causal_edges']} causal_edges, "
              f"{counts['judgments']} judgments)", file=sys.stderr)


if __name__ == "__main__":
    main()
