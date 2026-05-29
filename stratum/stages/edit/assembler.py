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


CST_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


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
) -> str:
    """Build the user prompt data section: articles, clusters, story context."""
    # Article snapshot
    def _article_snapshot(a: dict) -> str:
        title = a.get("title", "无标题")
        source = a.get("source", "未知来源")
        locale = a.get("source_locale", a.get("locale", ""))
        locale_tag = f" [{locale}]" if locale else ""
        date = a.get("published_at", "")
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", date or "")
        date_str = date_match.group(1) if date_match else date[:10] if date else ""
        snippet = a.get("snippet", a.get("extracted_summary", ""))
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        return (
            f"- **[{title}]({a.get('url', '')})**{locale_tag}\n"
            f"  来源: {source} | 日期: {date_str}\n"
            f"  摘要: {snippet}\n"
        )

    parts = []

    # Source index
    source_index = {}
    for a in articles:
        src = a.get("source", "")
        if src and src not in source_index:
            source_index[src] = a
    parts.append("## 来源索引\n")
    for src in sorted(source_index.keys()):
        parts.append(f"- {src}\n")
    parts.append("\n")

    # Clustered articles
    clustered_ids = set()
    for c in clusters.get("clusters", []):
        article_ids = c.get("article_ids", [])
        cluster_articles = [a for a in articles if a.get("id") in article_ids]
        if not cluster_articles:
            continue
        clustered_ids.update(article_ids)
        thread_id = c.get("thread_id", "")
        thread_label = c.get("thread_label", "")
        continuity = "⟳ 持续追踪" if thread_id else ""
        if thread_label:
            continuity = f"⟳ {thread_label}{' · ' + continuity if continuity else ''}"
        parts.append(f"## 集群: {c.get('canonical_title', '')[:80]}")
        if continuity:
            parts.append(f" ({continuity})")
        parts.append(f"\n(置信度: {c.get('confidence', '?')}, 共 {len(cluster_articles)} 篇)\n\n")
        for a in cluster_articles:
            parts.append(_article_snapshot(a))
        parts.append("\n")

    # Unclustered articles
    unclustered = [a for a in articles if a.get("id") not in clustered_ids]
    if unclustered:
        parts.append(f"## 其他文章 ({len(unclustered)} 篇)\n\n")
        for a in unclustered:
            parts.append(_article_snapshot(a))
        parts.append("\n")

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
    user_prompt = _build_data_section(articles, clusters, context, run_date)
    user_prompt += f"\n## 指令\n请生成 {cn_date} 的{title}。\n"
    user_prompt += f"共 {len(articles)} 篇文章，选出 {budget.get('min_items', 6)}-{budget.get('max_items', 10)} 条最重要的新闻。\n"

    # ── Structured output instructions ──
    output_cfg = cfg["output"]
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
    if output_cfg.get("causal_edges", {}).get("enabled") or output_cfg.get("judgments", {}).get("enabled"):
        user_prompt += (
            "\n## 最终输出格式\n"
            "请在简报 markdown 结束后，另起一行 `---DATA---`，然后输出一个 JSON 对象：\n"
            '```json\n{\n  "causal_edges": [...],\n  "judgments": [...]\n}\n```\n'
        )

    return system_prompt, user_prompt, output_cfg
