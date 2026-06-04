"""Report-facing text policies for DB-native synthesis.

This module owns Chinese product-output wording, section labels, language
normalization, and executive-level framing. The synthesis engine may call these
helpers, but should not grow new report-copy policy directly.
"""

from __future__ import annotations

import json
import re
from typing import Any

from stratum.db.synthesis.evidence import (
    fresh_article_theme as _fresh_article_theme,
    integration_decision_text as _format_integration_decision_text,
    matching_fresh_evidence as _score_matching_fresh_evidence,
    meaningful_tokens as _meaningful_tokens,
    rank_articles_for_theme as _rank_articles_for_theme,
)
from stratum.db.synthesis.events import SynthesizedEventBuilder


def _theme_body(
    target_scale: str,
    source_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    if target_scale == "weekly":
        return _weekly_theme_body(target_scale, source_scale, events, fresh_evidence)
    return _trend_body(target_scale, source_scale, events, fresh_evidence)


def _weekly_theme_body(
    target_scale: str,
    source_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    theme = _thread_theme(events[0].get("thread_id", "") if events else "", events)
    daily_signals = _event_points(events)
    fresh_titles = _article_titles(fresh_evidence, theme)
    parts = [
        "**本周判断**",
        _theme_judgment(theme, len(daily_signals), len(fresh_titles)),
        "",
        "**A. 来自日报数据库沉淀的信号**",
        _numbered_lines(daily_signals[:5]) if daily_signals else f"本周没有可展示的{_scale_label(source_scale)}沉淀信号。",
        "",
        "**B. 来自周度新增探索的证据**",
        _numbered_lines(fresh_titles[:5]) if fresh_titles else "本周没有可用的周度新增探索证据，因此该主线不能只凭新增外部验证上调置信度。",
        "",
        "**B2. 新信息整合判断**",
        _integration_decision_text(target_scale, events, fresh_evidence),
        "",
        "**C. 综合判断**",
        _theme_synthesis(theme, bool(fresh_titles)),
        "",
        "**D. Executive Implications**",
        _numbered_lines(_executive_implications(theme)),
        "",
        "**E. 置信度变化**",
        _confidence_delta_text(bool(fresh_titles)),
        "",
        "**F. 下周观察点**",
        _numbered_lines(_theme_watch_points(theme)),
    ]
    return "\n".join(parts)


def _trend_body(
    target_scale: str,
    source_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    event_points = _event_points(events)
    scale_label = _scale_label(source_scale)
    period_label = _period_label(target_scale)
    if not event_points:
        return f"这条主线在{scale_label}事件库中持续出现，但可展示的事件标题不足，需要回到证据链接继续核对。"
    event_dates = {event.get("date") for event in events if event.get("date")}
    if len(event_points) == 1:
        movement = f"这条主线在{period_label}集中体现为一个事件：{event_points[0]}。"
    elif len(event_dates) == 1:
        movement = (
            f"这条主线在{period_label}同一天出现 {len(event_points)} 个相关信号，"
            "对应信号如下：\n\n" + _numbered_lines(event_points[:5])
        )
    else:
        movement = (
            f"这条主线在{period_label}横跨 {len(event_points)} 个{scale_label}事件，"
            f"时间线从 {event_points[0]} 推进到 {event_points[-1]}。"
        )
    middle = [] if len(event_dates) == 1 else event_points[1:-1]
    if middle:
        movement += " 中间信号包括：" + "；".join(middle[:3]) + "。"
    if fresh_evidence:
        theme = _thread_theme(events[0].get("thread_id", "") if events else "", events)
        movement += f" {_fresh_reference_label(target_scale)}进一步补充：" + "；".join(_article_titles(fresh_evidence[:3], theme)) + "。"
    movement += f"\n\n整合判断：{_integration_decision_text(target_scale, events, fresh_evidence)}"
    movement += f"\n\n读者不需要先看过日报：这条主线的关键读法是，它已经从单日新闻变成{period_label}持续发酵、需要提高跟踪权重的事件线。"
    return movement


def _theme_judgment(theme: str, signal_count: int, fresh_count: int) -> str:
    freshness_note = "这条判断已有周度新增探索补强。" if fresh_count else "这条判断仍需要周度新增探索来验证。"
    return {
        "存储价格与周期": f"本周更重要的不是“价格上涨”本身，而是价格压力开始按品类和应用场景分层：DRAM 供需紧张、NAND 企业级韧性、消费级承压正在同时存在。{freshness_note}",
        "HBM 认证与产能": f"HBM 的竞争焦点正在从路线图宣传转向客户认证、样品节奏、良率和产能兑现；谁能把认证变成可交付供给，谁就更可能拿到下一轮 AI 供应链议价权。{freshness_note}",
        "中国存储扩张": f"中国存储扩张本周更像“产业位置上移”的信号，而不是单一公司新闻：资本化、份额提升和产品导入正在共同改变区域供应格局。{freshness_note}",
        "先进封装与 3D 存储": f"先进封装与 3D 存储不应被视为外围技术新闻；它们正在靠近 AI 存储性能、功耗和系统集成的核心约束。{freshness_note}",
        "企业级存储与控制器": f"AI 推理正在把存储竞争从介质容量推向系统吞吐、控制器效率和数据路径设计；企业级存储的价值判断需要从单价转向系统成本。{freshness_note}",
    }.get(theme, f"这条主线已经具备周度观察价值，但还需要更多外部验证来判断它是否会改变行业格局。{freshness_note}")


def _theme_synthesis(theme: str, has_fresh: bool) -> str:
    evidence_clause = "因为日报沉淀和周度新增探索方向一致，" if has_fresh else "由于目前缺少周度新增探索校验，"
    return {
        "存储价格与周期": f"{evidence_clause}本周只能把结论推进到“上行周期仍在，但分化比总量更重要”。如果后续报价和交期继续验证，管理层应优先评估成本传导、采购锁价和客户涨价承受力。",
        "HBM 认证与产能": f"{evidence_clause}本周只能把结论推进到“认证能力正在成为 HBM 竞争的关键控制点”。对技术团队，这意味着良率/封装/客户验证要放在路线图之前；对业务团队，这意味着长单和 ASP 的分化会继续扩大。",
        "中国存储扩张": f"{evidence_clause}本周只能把结论推进到“中国存储正在从追赶叙事转向供应链变量”。真正决定影响力的不是 IPO 或份额口径，而是头部客户导入、良率和规模交付。",
        "先进封装与 3D 存储": f"{evidence_clause}本周只能把结论推进到“封装能力可能成为 AI 存储路线的前置瓶颈”。这会影响技术路线选择，也会影响上游材料、设备和封装产能的战略价值。",
        "企业级存储与控制器": f"{evidence_clause}本周只能把结论推进到“AI 推理存储瓶颈正在系统化”。后续应把企业级 SSD、控制器和新架构放在同一个系统成本框架里看，而不是分散看单点产品。",
    }.get(theme, f"{evidence_clause}这条主线暂时保留为观察主题，尚不足以形成强结论。")


def _executive_implications(theme: str) -> list[str]:
    return {
        "存储价格与周期": [
            "技术和产品团队需要区分 DRAM、NAND、企业级和消费级存储的价格弹性。",
            "业务团队应关注 ASP、交期和客户采购节奏是否继续支撑上行周期。",
            "战略层面要判断这是短期补库存，还是 AI 需求驱动的更长周期变化。",
        ],
        "HBM 认证与产能": [
            "技术上，竞争焦点在客户认证、样品节奏、良率和封装协同，而不是单一路线图。",
            "商业上，通过高带宽产品验证的供应商更可能获得长单和 ASP 议价权。",
            "对外叙事可以强调 HBM 供给结构变化，但不能把样品出货直接等同于量产领先。",
        ],
        "中国存储扩张": [
            "技术上，需要继续验证 DDR5、NAND 和潜在 HBM 路线是否进入可规模交付阶段。",
            "业务上，客户导入、良率和产能利用率比融资或 IPO 口径更能说明真实进展。",
            "战略上，中国存储扩张会影响供应链替代、价格纪律和区域竞争格局。",
        ],
        "先进封装与 3D 存储": [
            "技术上，封装、互连和堆叠能力可能成为 AI 存储性能提升的关键瓶颈。",
            "业务上，上游材料、设备和封装产能扩张可能先于终端产品收入体现。",
            "战略上，需要判断控制点是否从存储芯片本身延伸到先进封装生态。",
        ],
        "企业级存储与控制器": [
            "技术上，AI 推理场景会更重视系统吞吐、控制器和数据路径效率。",
            "业务上，企业级 SSD、控制器和架构方案可能拥有比消费级 NAND 更强韧性。",
            "市场叙事上，可以讲 AI 存储架构升级，但要避免把概念标准化误读为确定需求。",
        ],
    }.get(theme, [
        "技术、业务和市场团队都应先把该主线作为观察项，而不是已验证结论。",
        "后续需要用客户、产能、价格或供应链证据来确认其周度重要性。",
    ])


def _confidence_delta_text(has_fresh: bool) -> str:
    if has_fresh:
        return "置信度上调：日报沉淀信号获得周度新增探索补充。"
    return "置信度暂不因新增探索上调：本周缺少同级新增探索证据，结论主要依赖日报数据库沉淀。"


def _theme_watch_points(theme: str) -> list[str]:
    return {
        "存储价格与周期": ["DRAM 合约价与现货价是否继续同向上行", "NAND 企业级与消费级价格是否继续分化", "云厂商采购节奏是否支撑上行周期"],
        "HBM 认证与产能": ["客户认证或量产公告是否出现", "SK 海力士、三星、Micron 的 HBM4/HBM4E 节点差异", "NVIDIA 或 ASIC 客户绑定是否更明确"],
        "中国存储扩张": ["CXMT/YMTC 是否出现客户导入证据", "良率、产能和产品代际是否有新数据", "融资、IPO 或监管信号是否改变扩张节奏"],
        "先进封装与 3D 存储": ["封装设备和材料订单是否跟进", "SoIC/EMIB/堆叠路线是否出现客户验证", "先进封装产能是否成为 HBM 或 AI 存储瓶颈"],
        "企业级存储与控制器": ["企业级 SSD 价格与出货是否强于消费级", "控制器厂商数据中心收入是否继续走强", "HBF/SSD 等 AI 推理存储架构是否获得生态支持"],
    }.get(theme, ["是否出现多来源验证", "是否影响核心公司或技术路线", "是否改变已有判断置信度"])


def _fresh_evidence_body(target_scale: str, articles: list[dict[str, Any]]) -> str:
    titles = _article_titles(articles)
    if not titles:
        return "本周期没有可用的同级新增探索证据。"
    return (
        f"{_fresh_reference_label(target_scale)}不是下级报告的重复，而是对{_scale_adjective(target_scale)}判断的独立验证："
        + "；".join(titles[:8])
        + "。"
    )


def _fresh_evidence_title(target_scale: str, articles: list[dict[str, Any]]) -> str:
    return {
        "weekly": "新增验证：本周补充信号",
        "monthly": "新增验证：本月补充信号",
        "quarterly": "新增验证：本季补充信号",
        "yearly": "新增验证：本年补充信号",
    }.get(target_scale, f"新增验证：{len(articles)} 条补充信号")


def _judgment_body(judgments: list[dict[str, Any]], pending: list[dict[str, Any]]) -> str:
    judgments = _unique_judgments(judgments)
    pending = _unique_judgments(pending)
    if not judgments and not pending:
        return "本周期没有可复核的下级判断。"
    reviewed = [_display_hypothesis(judgment.get("hypothesis", "")) for judgment in judgments if judgment.get("hypothesis")]
    waiting = [_display_hypothesis(judgment.get("hypothesis", "")) for judgment in pending if judgment.get("hypothesis")]
    parts = []
    if reviewed:
        parts.append("已复核：\n\n" + _numbered_lines(reviewed[:6]))
    else:
        parts.append("已复核：本期没有完成状态更新的判断。")
    if waiting:
        parts.append("待验证：\n\n" + _numbered_lines(waiting[:6]))
    return "\n\n".join(parts)


def _unique_judgments(judgments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for judgment in judgments:
        hypothesis = judgment.get("hypothesis", "")
        if not hypothesis or hypothesis in seen:
            continue
        seen.add(hypothesis)
        unique.append(judgment)
    return unique


def _section_title(scale: str) -> str:
    return {
        "weekly": "本周综合",
        "monthly": "月度综合",
        "quarterly": "季度综合",
        "yearly": "年度综合",
    }.get(scale, "综合")


def _section_titles(scale: str) -> dict[str, str]:
    if scale == "weekly":
        return {
            "executive_summary": "Executive Summary",
            "core_themes": "Core Themes",
            "signal_noise": "Signal vs Noise",
            "judgment_tracker": "Judgment Tracker",
            "fresh_coverage": "Fresh Exploration Coverage",
            "watchlist": "Next Week Watchlist",
            "source_boundary": "来源与置信度边界",
        }
    return {
        "synthesis": _section_title(scale),
        "trend": "趋势与主线",
        "fresh": "新增验证",
        "judgment": "判断与验证",
        "lineage": "来源说明",
    }


def _summary_title(scale: str) -> str:
    return {
        "weekly": "本周结论",
        "monthly": "月度结论",
        "quarterly": "季度结论",
        "yearly": "年度结论",
    }.get(scale, "综合结论")


def _summary_body(
    scale: str,
    window_start: str,
    window_end: str,
    inputs: dict[str, Any],
    top_threads: list[dict[str, Any]],
) -> str:
    thread_count = len(top_threads)
    top_theme = _thread_theme(top_threads[0]["thread_id"], top_threads[0]["events"]) if top_threads else "the tracked story set"
    source_scale_label = "、".join(_scale_label(scale) for scale in inputs["source_scales"])
    fresh_count = len(inputs.get("fresh_evidence", []))
    if scale == "weekly":
        conclusions = _executive_summary_conclusions(top_threads, fresh_count)
        return _numbered_lines(conclusions)
    return (
        f"这份{_scale_adjective(scale)}报告整合了 {window_start} 至 {window_end} 期间的 "
        f"{len(inputs['reports'])} 份下级报告和 {len(inputs['events'])} 个{source_scale_label}事件，"
        f"跟踪 {thread_count} 条主线，并用 {fresh_count} 条同级新增探索证据校验。"
    )


def _executive_summary_conclusions(top_threads: list[dict[str, Any]], fresh_count: int) -> list[str]:
    themes = [_thread_theme(group["thread_id"], group["events"]) for group in top_threads]
    theme_set = set(themes)
    conclusions = []
    if "存储价格与周期" in theme_set:
        conclusions.append("存储行业本周的核心变量是价格周期的分化，而不是简单的全面涨价：DRAM 紧张、NAND 分层和企业级韧性需要分开判断。")
    if "HBM 认证与产能" in theme_set:
        conclusions.append("HBM 竞争正在从“谁宣布路线图”转向“谁能通过客户认证并稳定交付”，这会直接影响 AI 供应链中的议价权分配。")
    if "中国存储扩张" in theme_set:
        conclusions.append("中国存储厂商的扩张应被视为供应链结构变量：资本化只是表层，客户导入、良率和规模交付才决定真实冲击。")
    if "先进封装与 3D 存储" in theme_set:
        conclusions.append("先进封装和 3D 存储正在从技术背景项变成 AI 存储性能的前置约束，需要进入技术路线和供应链判断。")
    if "企业级存储与控制器" in theme_set:
        conclusions.append("AI 推理把企业级存储的竞争焦点推向系统吞吐、控制器效率和数据路径设计，单看 NAND 价格会低估架构变化。")
    if not conclusions:
        conclusions.append("本周信号尚未形成明确结构性变化，建议维持观察并等待多来源验证。")
    if fresh_count == 0:
        conclusions.append("本期缺少周度新增探索证据，因此所有结论都应视为“日报沉淀推导”，不能视为已经完成外部验证。")
    return conclusions[:5]


def _thread_theme(thread_id: str, events: list[dict[str, Any]]) -> str:
    return SynthesizedEventBuilder().thread_theme(thread_id, events)


def _scale_label(scale: str) -> str:
    return {
        "daily": "日频",
        "weekly": "周度",
        "monthly": "月度",
        "quarterly": "季度",
        "yearly": "年度",
    }.get(scale, scale)


def _article_titles(articles: list[dict[str, Any]], theme: str | None = None) -> list[str]:
    titles = []
    for article in articles:
        title = _article_display_title(article, theme)
        if title:
            titles.append(title)
    return titles


def _article_display_title(article: dict[str, Any], theme: str | None = None) -> str:
    title = str(article.get("title") or "").strip()
    if title and _is_chinese_display_text(title):
        return title
    source = article.get("source") or article.get("source_domain") or "外部来源"
    inferred_theme = theme or _fresh_article_theme(article)
    focus = _article_focus_terms(article)
    if focus:
        return f"{source}：{inferred_theme}相关证据（{focus}）"
    return f"{source}：{inferred_theme}相关证据"


def _is_chinese_display_text(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text)) and not _has_japanese_or_korean(text)


def _has_japanese_or_korean(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\uac00-\ud7af]", text))


def _article_focus_terms(article: dict[str, Any]) -> str:
    values = _json_list(article.get("entities")) + _json_list(article.get("entity_ids"))
    values += _json_list(article.get("terms")) + _json_list(article.get("term_ids"))
    clean = []
    for value in values:
        text = str(value).strip()
        if not text or _has_japanese_or_korean(text):
            continue
        if text.lower() in {"ai", "memory", "storage", "semiconductor"}:
            continue
        if text not in clean:
            clean.append(text)
        if len(clean) >= 3:
            break
    return "、".join(clean)


def _numbered_lines(values: list[str]) -> str:
    return "\n".join(f"{index}. {value}" for index, value in enumerate(values, start=1))


def _display_hypothesis(value: str) -> str:
    text = value.strip()
    known_translations = {
        "If HBM qualification and capacity expansion continue through the next verification window, memory suppliers with validated high-bandwidth products will keep stronger pricing power than commodity-only suppliers.": (
            "如果 HBM 认证和产能扩张在下一个验证窗口继续推进，"
            "已通过高带宽产品验证的存储供应商将比只做通用品类的供应商保持更强定价权。"
        ),
    }
    return known_translations.get(text, text)


def _event_points(events: list[dict[str, Any]]) -> list[str]:
    points = []
    chinese_points = []
    seen_titles = set()
    for event in sorted(events, key=_event_sort_key):
        title = (event.get("title") or "").strip()
        title_key = _normalize_title_key(title)
        if not title or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        date = event.get("date") or ""
        point = f"{date}：{title}" if date else title
        points.append(point)
        if re.search(r"[\u4e00-\u9fff]", title):
            chinese_points.append(point)
    return chinese_points or points


def _lead_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    return SynthesizedEventBuilder().lead_event(events)


def _lead_event_for_theme(theme: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return SynthesizedEventBuilder().lead_event_for_theme(theme, events)


def _event_sort_key(event: dict[str, Any]) -> tuple:
    return SynthesizedEventBuilder().event_sort_key(event)


def _title_language_penalty(title: str) -> int:
    return SynthesizedEventBuilder().title_language_penalty(title)


def _normalize_title_key(title: str) -> str:
    text = re.sub(r"\s+", " ", title.lower()).strip()
    text = re.sub(r"^\[news\]\s*", "", text)
    return text


def _report_topic_key(event: dict[str, Any]) -> str:
    return SynthesizedEventBuilder().report_topic_key(event)


def _representative_thread_id(events: list[dict[str, Any]], fallback: str) -> str:
    lead = _lead_event(events)
    return lead.get("thread_id") or fallback


def _period_label(scale: str) -> str:
    return {
        "weekly": "本周",
        "monthly": "本月",
        "quarterly": "本季",
        "yearly": "本年",
    }.get(scale, "本周期")


def _scale_adjective(scale: str) -> str:
    return {
        "weekly": "周度",
        "monthly": "月度",
        "quarterly": "季度",
        "yearly": "年度",
    }.get(scale, "周期")


def _fresh_reference_label(scale: str) -> str:
    return {
        "weekly": "本周新增探索",
        "monthly": "本月新增探索",
        "quarterly": "本季新增探索",
        "yearly": "本年新增探索",
    }.get(scale, "本周期新增探索")


def _lineage_body(inputs: dict[str, Any], source_report_ids: list[str]) -> str:
    if not source_report_ids:
        return "没有可用的下级报告；本次综合只使用事件库输入。"
    scale_counts = []
    for scale in inputs.get("source_scales", []):
        count = len(inputs.get("inputs_by_scale", {}).get(scale, {}).get("reports", []))
        if count:
            scale_counts.append(f"{count} 份{_scale_adjective(scale)}报告")
    report_text = "、".join(scale_counts) if scale_counts else f"{len(source_report_ids)} 份下级报告"
    event_count = len(inputs.get("events", []))
    fresh_count = len(inputs.get("fresh_evidence", []))
    return (
        f"本报告参考 {report_text}，并结合 {event_count} 个结构化事件"
        f"和 {fresh_count} 条同级新增探索证据生成。报告正文已重写为独立周期判断，"
        "整合点在周度新信息完成 search、enrich、verify、normalize 并写入 articles 后，"
        "由 DB synthesis 读取日报数据库沉淀与 weekly fresh evidence，按主题相关性和证据强度做整合判断。"
        "来源 ID 保存在数据库 lineage 中，供追溯和审计使用。"
    )


def _signal_noise_body(top_threads: list[dict[str, Any]]) -> str:
    upgraded = []
    watch_only = []
    for group in top_threads:
        theme = _thread_theme(group["thread_id"], group["events"])
        event_count = len(_event_points(group["events"]))
        if event_count >= 2:
            upgraded.append(f"{theme}：已有 {event_count} 条日报沉淀信号，升级为周度主线。")
        else:
            watch_only.append(f"{theme}：目前只有 1 条日报沉淀信号，保留为观察项，避免过度解读。")
    parts = ["**升级为周度信号**", _numbered_lines(upgraded) if upgraded else "本期没有足够多源或多事件支撑的升级信号。"]
    parts.extend(["", "**暂不升级或需谨慎解读**", _numbered_lines(watch_only) if watch_only else "本期核心主线均至少有多条相关信号支撑。"])
    return "\n".join(parts)


def _fresh_coverage_title(fresh_evidence: list[dict[str, Any]]) -> str:
    if fresh_evidence:
        return f"本周新增探索覆盖 {len(fresh_evidence)} 条证据"
    return "本周缺少新增探索证据"


def _fresh_coverage_body(fresh_evidence: list[dict[str, Any]]) -> str:
    if not fresh_evidence:
        return (
            "本期周报没有同级 weekly 探索输入。"
            "这意味着核心主线只能基于日报数据库沉淀形成周度判断，"
            "不能声称已经获得新的外部验证或反向证据校验。"
        )
    buckets: dict[str, list[dict[str, Any]]] = {}
    for article in fresh_evidence:
        theme = _fresh_article_theme(article)
        buckets.setdefault(theme, []).append(article)

    lines = []
    for theme, articles in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
        examples = _article_titles(_rank_articles_for_theme(theme, articles), theme)[:3]
        if not examples:
            continue
        lines.append(f"{theme}：{len(articles)} 条；代表证据包括：" + "；".join(examples))
    if not lines:
        return "本周新增探索有输入，但尚未形成可归类的周度验证证据。"
    return (
        "周报先独立搜索过去一周的新信息，完成 enrich、verify、normalize 后写入数据库；"
        "随后在 DB synthesis 阶段与日报数据库沉淀做主题级整合判断。"
        "新增探索的价值不在于数量本身，而在于补齐哪些判断边界：\n\n"
        + _numbered_lines(lines[:8])
    )


def _watchlist_body(top_threads: list[dict[str, Any]], fresh_evidence: list[dict[str, Any]]) -> str:
    points = []
    seen = set()
    for group in top_threads:
        theme = _thread_theme(group["thread_id"], group["events"])
        for point in _theme_watch_points(theme):
            if point not in seen:
                seen.add(point)
                points.append(point)
            if len(points) >= 8:
                break
        if len(points) >= 8:
            break
    if not fresh_evidence:
        points.append("补齐周度新增探索：至少加入客户、供应链、分析师或跨语言来源的一组验证。")
    return _numbered_lines(points[:8])


def _matching_fresh_evidence(events: list[dict[str, Any]], fresh_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    theme = _thread_theme(events[0].get("thread_id", "") if events else "", events)
    event_terms = _meaningful_tokens(_unique_flatten(events, "term_ids"))
    event_entities = _meaningful_tokens(_unique_flatten(events, "entity_ids"))
    return _score_matching_fresh_evidence(
        theme=theme,
        event_terms=event_terms,
        event_entities=event_entities,
        fresh_evidence=fresh_evidence,
    )


def _integration_decision_text(
    target_scale: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    return _format_integration_decision_text(
        target_scale=target_scale,
        scale_label=_scale_label(target_scale),
        events=events,
        fresh_evidence=fresh_evidence,
    )


def _unique_flatten(events: list[dict[str, Any]], field: str) -> list[str]:
    values = []
    for event in events:
        current = event.get(field) or []
        if isinstance(current, str):
            try:
                current = json.loads(current)
            except json.JSONDecodeError:
                current = []
        for value in current:
            if value and value not in values:
                values.append(str(value))
    return values


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


class SynthesisTextBuilder:
    """Facade for report-facing synthesis text policy.

    The public methods intentionally avoid leading underscores so callers can
    depend on a stable text abstraction while legacy engine helpers remain
    available as compatibility wrappers.
    """

    def theme_body(self, target_scale: str, source_scale: str, events: list[dict[str, Any]], fresh_evidence: list[dict[str, Any]]) -> str:
        return _theme_body(target_scale, source_scale, events, fresh_evidence)

    def trend_body(self, target_scale: str, source_scale: str, events: list[dict[str, Any]], fresh_evidence: list[dict[str, Any]]) -> str:
        return _trend_body(target_scale, source_scale, events, fresh_evidence)

    def summary_body(self, scale: str, window_start: str, window_end: str, inputs: dict[str, Any], top_threads: list[dict[str, Any]]) -> str:
        return _summary_body(scale, window_start, window_end, inputs, top_threads)

    def judgment_body(self, judgments: list[dict[str, Any]], pending: list[dict[str, Any]]) -> str:
        return _judgment_body(judgments, pending)

    def fresh_evidence_body(self, target_scale: str, articles: list[dict[str, Any]]) -> str:
        return _fresh_evidence_body(target_scale, articles)

    def fresh_coverage_body(self, fresh_evidence: list[dict[str, Any]]) -> str:
        return _fresh_coverage_body(fresh_evidence)

    def signal_noise_body(self, top_threads: list[dict[str, Any]]) -> str:
        return _signal_noise_body(top_threads)

    def watchlist_body(self, top_threads: list[dict[str, Any]], fresh_evidence: list[dict[str, Any]]) -> str:
        return _watchlist_body(top_threads, fresh_evidence)

    def lineage_body(self, inputs: dict[str, Any], source_report_ids: list[str]) -> str:
        return _lineage_body(inputs, source_report_ids)


__all__ = [
    "SynthesisTextBuilder",
]
