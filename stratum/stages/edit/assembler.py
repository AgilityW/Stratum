"""assembler.py — Pure-function prompt assembly engine.

Domain-agnostic. Reads manifest.yaml, loads fragments, injects domain config,
assembles system + user prompts for LLM consumption.

Usage:
    from assembler import assemble

    system_prompt, user_prompt, output_cfg = assemble(
        manifest_path="prompts/manifest.yaml",
        prompts_dir="prompts",
        timescale="daily",
        domain_cfg=...,
        domain_id="storage",
        run_date="2026-05-30",
        title="存储早报",
        articles=[...],
        clusters={...},
        context={...},
    )
"""

from __future__ import annotations

import json
import os
import re
import yaml
from datetime import datetime
from urllib.parse import urlparse


CST_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DEFAULT_PROMPT_BUDGET = {
    "prompt_max_chars": 120000,
    "max_articles_per_cluster": 12,
    "max_low_confidence_articles_per_cluster": 4,
    "max_unclustered_articles": 20,
}
SOURCE_TYPE_PRIORITY = {
    "official": 0,
    "analyst": 1,
    "media": 2,
    "blog": 3,
}


def _deep_get(d: dict, path: str):
    """Get nested dict value by dotted path. Returns None if missing."""
    parts = path.split(".")
    for p in parts:
        if isinstance(d, dict):
            d = d.get(p)
        else:
            return None
    return d


def _render_template(text: str, variables: dict) -> str:
    """Render {{ var }} placeholders with values from variables dict.
    Also handles {% if var %}...{% endif %} conditionals."""
    # Conditionals: {% if varname %}...{% endif %}
    def _replace_conditional(match):
        var_name = match.group(1).strip()
        body = match.group(2)
        return body if variables.get(var_name) else ""
    text = re.sub(
        r'\{%\s*if\s+(\w+)\s*%\}(.*?)\{%\s*endif\s*%\}',
        _replace_conditional, text, flags=re.DOTALL
    )

    # Simple {{ var }} replacement
    def _replace_var(match):
        var_name = match.group(1).strip()
        return str(variables.get(var_name, ""))
    text = re.sub(r'\{\{\s*(\w+)\s*\}\}', _replace_var, text)

    return text


def _format_cn_date(run_date: str) -> str:
    """Convert YYYY-MM-DD to Chinese date format: 2026年5月30日 · 周五"""
    dt = datetime.fromisoformat(run_date)
    weekday = CST_WEEKDAYS[dt.weekday()]
    return f"{dt.year}年{dt.month}月{dt.day}日 · {weekday}"


def _source_name(article: dict) -> str:
    """Return the best source label across normalized and search result shapes."""
    if article.get("source"):
        return article["source"]
    if article.get("source_domain"):
        return article["source_domain"]
    url = article.get("url", "")
    if url:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        return host or "未知来源"
    return "未知来源"


def _inject_domain_values(fragment_text: str, domain_cfg: dict, inject_paths: list[str]) -> tuple[str, dict]:
    """Inject domain.yaml values into fragment placeholders.

    Returns (rendered_text, injected_variables) — the caller must merge
    injected_variables with common variables before final render."""
    variables = {}
    for path in inject_paths:
        val = _deep_get(domain_cfg, path)
        if val is None:
            continue
        # Flatten the path key: editorial.platform_admission → platform_admission
        key = path.split(".")[-1]
        if isinstance(val, dict):
            # Inject individual sub-keys
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, str):
                    variables[f"{key}_{sub_key}"] = sub_val
                elif isinstance(sub_val, list):
                    variables[f"{key}_{sub_key}"] = ", ".join(str(v) for v in sub_val)
        elif isinstance(val, list):
            variables[key] = ", ".join(str(v) for v in val)
        else:
            variables[key] = val
    return _render_template(fragment_text, variables), variables


def _build_data_section(
    articles: list[dict],
    clusters: dict,
    context: dict,
    run_date: str,
    prompt_budget: dict | None = None,
) -> str:
    """Build the user prompt data section: articles, clusters, story context."""
    budget = dict(DEFAULT_PROMPT_BUDGET)
    if prompt_budget:
        budget.update({k: v for k, v in prompt_budget.items() if v is not None})

    # Article snapshot
    def _article_snapshot(a: dict) -> str:
        title = a.get("title", "无标题")
        source = _source_name(a)
        date = a.get("published_at", "")
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", date or "")
        date_str = date_match.group(1) if date_match else date[:10] if date else ""
        snippet = a.get("snippet", a.get("extracted_summary", ""))
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        quality_flags = a.get("quality_flags") or []
        flag_line = ""
        if quality_flags:
            flag_line = f"  证据属性: {', '.join(str(flag) for flag in quality_flags)}（背景证据，不能作为唯一今日来源）\n"
        return (
            f"- **[{title}]({a.get('url', '')})**\n"
            f"  来源: {source} | 日期: {date_str}\n"
            f"{flag_line}"
            f"  摘要: {snippet}\n"
        )

    def _article_rank(a: dict) -> tuple:
        source_type = a.get("source_type") or a.get("source_type_hint") or "media"
        source_rank = SOURCE_TYPE_PRIORITY.get(str(source_type), 9)
        has_claims = bool(a.get("numeric_claims"))
        snippet = a.get("snippet") or a.get("extracted_summary") or ""
        return (source_rank, not has_claims, -len(str(snippet)), _source_name(a), a.get("title", ""))

    def _limit_cluster_articles(cluster: dict, cluster_articles: list[dict]) -> tuple[list[dict], int]:
        confidence = str(cluster.get("confidence", "")).lower()
        default_limit = int(budget.get("max_articles_per_cluster", 12))
        low_limit = int(budget.get("max_low_confidence_articles_per_cluster", 4))
        limit = low_limit if confidence == "low" else default_limit
        selected = sorted(cluster_articles, key=_article_rank)[:max(0, limit)]
        return selected, max(0, len(cluster_articles) - len(selected))

    body_parts = []
    included_articles: list[dict] = []
    omitted_notes: list[str] = []
    max_chars = int(budget.get("prompt_max_chars", 120000))

    # Clustered articles
    clustered_ids = set()
    article_by_id = {a.get("id"): a for a in articles}
    for c in clusters.get("clusters", []):
        article_ids = c.get("article_ids", [])
        cluster_articles = [article_by_id.get(article_id) for article_id in article_ids]
        cluster_articles = [a for a in cluster_articles if a]
        if not cluster_articles:
            continue
        clustered_ids.update(article_ids)
        selected_articles, omitted = _limit_cluster_articles(c, cluster_articles)
        if not selected_articles:
            omitted_notes.append(
                f"- 集群 `{c.get('id', '')}` 未放入正文证据包，原始 {len(cluster_articles)} 篇。"
            )
            continue
        thread_id = c.get("thread_id", "")
        thread_label = c.get("thread_label", "")
        continuity = "⟳ 持续追踪" if thread_id else ""
        if thread_label:
            continuity = f"⟳ {thread_label}{' · ' + continuity if continuity else ''}"
        section_parts = [f"## 集群: {c.get('canonical_title', '')[:80]}"]
        if continuity:
            section_parts.append(f" ({continuity})")
        section_parts.append(
            f"\n(置信度: {c.get('confidence', '?')}, 原始 {len(cluster_articles)} 篇，"
            f"本 prompt 选入 {len(selected_articles)} 篇)\n\n"
        )
        for a in selected_articles:
            section_parts.append(_article_snapshot(a))
        section_parts.append("\n")
        section = "".join(section_parts)
        if sum(len(part) for part in body_parts) + len(section) <= max_chars:
            body_parts.append(section)
            included_articles.extend(selected_articles)
        else:
            omitted += len(selected_articles)
        if omitted:
            omitted_notes.append(
                f"- 集群 `{c.get('id', '')}` 因 prompt budget 省略 {omitted} 篇；"
                f"标题：{c.get('canonical_title', '')[:80]}"
            )

    # Unclustered articles
    unclustered = [a for a in articles if a.get("id") not in clustered_ids]
    if unclustered:
        limit = int(budget.get("max_unclustered_articles", 20))
        selected_unclustered = sorted(unclustered, key=_article_rank)[:max(0, limit)]
        section_parts = [f"## 其他文章 (原始 {len(unclustered)} 篇，本 prompt 选入 {len(selected_unclustered)} 篇)\n\n"]
        for a in selected_unclustered:
            section_parts.append(_article_snapshot(a))
        section_parts.append("\n")
        section = "".join(section_parts)
        if selected_unclustered and sum(len(part) for part in body_parts) + len(section) <= max_chars:
            body_parts.append(section)
            included_articles.extend(selected_unclustered)
        omitted = len(unclustered) - len(selected_unclustered)
        if omitted:
            omitted_notes.append(f"- 其他未聚类文章因 prompt budget 省略 {omitted} 篇。")

    parts = []

    # Source index for the evidence actually included in the prompt.
    source_index = {}
    for a in included_articles:
        src = _source_name(a)
        if src and src not in source_index:
            source_index[src] = a
    parts.append("## 来源索引\n")
    for src in sorted(source_index.keys()):
        parts.append(f"- {src}\n")
    parts.append("\n")

    if omitted_notes:
        parts.append("## Prompt 预算说明\n")
        parts.append(
            f"- verified articles 共 {len(articles)} 篇；本 prompt 选入 "
            f"{len({a.get('id') for a in included_articles})} 篇代表证据，"
            "raw/articles 原始文件仍保留全集。\n"
        )
        parts.extend(f"{note}\n" for note in omitted_notes)
        parts.append("\n")

    parts.extend(body_parts)

    # Story context
    carried = context.get("carried_forward", [])
    if carried:
        parts.append("## 持续追踪事件\n\n")
        for ev in carried:
            parts.append(f"- **{ev.get('title', '')}** (优先级: {ev.get('priority', '?')})\n")
            for q in ev.get("open_questions", []):
                parts.append(f"  - {q}\n")
        parts.append("\n")

    return "".join(parts)


def _schema_to_instructions(schema_path: str) -> str:
    """Convert JSON Schema to human-readable output instructions for LLM."""
    with open(schema_path) as f:
        schema = json.load(f)

    props = schema.get("properties", {})
    required = schema.get("required", [])
    lines = [f"## {schema.get('$id', 'structured_data')} 字段说明\n"]
    for name, prop in props.items():
        desc = prop.get("description", "")
        req = " (必填)" if name in required else ""
        extras = []
        if "enum" in prop:
            extras.append(f"可选值: {' / '.join(prop['enum'])}")
        if "maxLength" in prop:
            extras.append(f"最多 {prop['maxLength']} 字符")
        if "pattern" in prop:
            extras.append(f"格式: {prop['pattern']}")
        line = f"- **{name}**{req}: {desc}"
        if extras:
            line += f" ({'; '.join(extras)})"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def _structured_output_keys(output_cfg: dict) -> list[str]:
    """Return enabled structured output keys in stable prompt order."""
    keys = []
    for key in ("threads", "causal_edges", "judgments"):
        if output_cfg.get(key, {}).get("enabled"):
            keys.append(key)
    return keys


def _thread_output_instructions() -> str:
    """Return concise instructions for event-thread structured output."""
    return (
        "\n## 事件线程输出格式\n"
        "请生成 threads 数组，用于后续跨天追踪和下一轮 Search follow-up。"
        "每个重要延续故事或新故事输出一个对象，字段如下：\n"
        "- **thread_id**: 已有 thread 使用上下文中的 thread_id；新故事可留空或使用稳定临时 id\n"
        "- **title**: 事件线程标题\n"
        "- **status**: emerging / active / cooling\n"
        "- **priority**: high / medium / low\n"
        "- **entity_ids**: 相关公司/实体 id 数组\n"
        "- **term_ids**: 相关技术/主题 id 数组\n"
        "- **watch_signals**: 2-5 条后续搜索短语，必须具体到公司、产品、验证/量产/价格/客户等信号\n"
        "- **close_conditions**: 该线程可视为结束的条件数组\n"
    )


def assemble(
    manifest_path: str,
    prompts_dir: str,
    timescale: str,
    domain_cfg: dict,
    domain_id: str,
    run_date: str,
    title: str,
    articles: list[dict],
    clusters: dict,
    context: dict,
) -> tuple[str, str, dict]:
    """Assemble system + user prompts for LLM.

    Returns:
        (system_prompt, user_prompt, output_config)
    """
    # Load manifest
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    if timescale not in manifest:
        raise ValueError(f"Unknown timescale: {timescale}. Available: {list(manifest.keys())}")

    cfg = manifest[timescale]
    cn_date = _format_cn_date(run_date)

    # ── Build system prompt from fragments + template ──
    system_parts = []

    # Shared fragments
    for frag in cfg["system"]["fragments"]:
        frag_path = os.path.join(prompts_dir, frag["path"])
        with open(frag_path) as f:
            text = f.read()
        # Inject domain values
        inject_paths = frag.get("inject", [])
        injected_vars = {}
        if inject_paths:
            text, injected_vars = _inject_domain_values(text, domain_cfg, inject_paths)
        # Inject common variables (merge with injected domain vars)
        render_vars = {
            "domain_title": title,
            "domain_id": domain_id,
            "date_line": cn_date,
        }
        render_vars.update(injected_vars)
        text = _render_template(text, render_vars)
        system_parts.append(text)

    # Timescale-specific template
    template_path = os.path.join(prompts_dir, cfg["system"]["template"])
    with open(template_path) as f:
        template = f.read()
    budget = cfg.get("budget", {})
    template = _render_template(template, {
        "domain_title": title,
        "date_line": cn_date,
        "article_count": str(len(articles)),
        "min_items": str(budget.get("min_items", 6)),
        "max_items": str(budget.get("max_items", 10)),
    })
    system_parts.append(template)

    system_prompt = "\n\n---\n\n".join(system_parts)

    # ── Build user prompt: data section ──
    user_prompt = _build_data_section(articles, clusters, context, run_date, cfg.get("budget", {}))
    user_prompt += f"\n## 指令\n请生成 {cn_date} 的{title}。\n"
    user_prompt += f"共 {len(articles)} 篇文章，选出 {budget.get('min_items', 6)}-{budget.get('max_items', 10)} 条最重要的新闻。\n"

    # ── Structured output instructions ──
    output_cfg = dict(cfg["output"])
    output_cfg["_budget"] = budget
    if output_cfg.get("threads", {}).get("enabled"):
        user_prompt += _thread_output_instructions()
    if output_cfg.get("causal_edges", {}).get("enabled"):
        schema_path = os.path.join(prompts_dir, output_cfg["causal_edges"]["schema"])
        user_prompt += "\n## 因果链输出格式\n"
        user_prompt += _schema_to_instructions(schema_path)
        user_prompt += "\n请生成 causal_edges 数组。\n"
    if output_cfg.get("judgments", {}).get("enabled"):
        schema_path = os.path.join(prompts_dir, output_cfg["judgments"]["schema"])
        user_prompt += "\n## 判断输出格式\n"
        user_prompt += _schema_to_instructions(schema_path)
        user_prompt += "\n请生成 judgments 数组（1-3 个判断）。\n"

    # Append structured output marker instruction
    structured_keys = _structured_output_keys(output_cfg)
    if structured_keys:
        json_keys = ",\n  ".join(f'"{key}": [...]' for key in structured_keys)
        user_prompt += (
            "\n## 最终输出格式\n"
            "请在简报 markdown 结束后，另起一行 `---DATA---`，然后输出一个 JSON 对象：\n"
            f"```json\n{{\n  {json_keys}\n}}\n```\n"
        )

    return system_prompt, user_prompt, output_cfg
