"""Evidence matching and citation helpers for DB-native synthesis."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from stratum.db.synthesis.policy import classify_evidence_class, evaluate_theme


def matching_fresh_evidence(
    *,
    theme: str,
    event_terms: set[str],
    event_entities: set[str],
    fresh_evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return fresh articles that are relevant enough for one synthesized theme."""
    scored = []
    for article in fresh_evidence:
        score = fresh_article_score(theme, event_terms, event_entities, article)
        if score >= 3:
            scored.append((score, article))
    scored.sort(key=lambda item: (-item[0], evidence_class_rank(item[1]), source_rank(item[1]), item[1].get("title", "")))
    return [article for _, article in scored]


def integration_decision_text(
    *,
    target_scale: str,
    scale_label: str,
    events: list[dict[str, Any]],
    fresh_evidence: list[dict[str, Any]],
) -> str:
    """Render the shared synthesis-policy decision for report body text."""
    evaluation = evaluate_theme(
        target_scale=target_scale,
        events=events,
        fresh_articles=fresh_evidence,
    )
    baseline = evaluation.baseline
    fresh = evaluation.fresh
    decision = evaluation.decision
    if decision.role == "baseline_only":
        return (
            "暂不把同级新增探索纳入本条主线的确认依据。"
            f"本条{scale_label}判断主要依赖下级数据库沉淀，"
            "需要在后续探索中补齐外部验证或反向证据。"
        )
    if decision.role == "baseline_confirmed_by_fresh":
        return (
            f"可将 {baseline.event_count} 条下级数据库信号与 "
            f"{fresh.evidence_count} 条同级新增探索证据合并为{scale_label}主线确认。"
            "新增证据具备独立来源或高质量来源支撑，因此可以上调置信度。"
        )
    if decision.role == "baseline_supplemented_by_fresh":
        return (
            f"同级新增探索可作为 {baseline.event_count} 条下级数据库信号的补充验证，"
            "但暂不足以单独改变判断方向。"
            "本条主线可以继续进入报告，置信度只做温和上调。"
        )
    if decision.role == "fresh_contradicts_baseline":
        return (
            f"同级新增探索与 {baseline.event_count} 条下级数据库信号方向相反，"
            "且新增证据强度较高。"
            f"本期不应把两类证据合并成单一{scale_label}确认结论，"
            "而应拆成冲突判断：保留下级沉淀作为历史基线，同时降低或拆分当前置信度。"
        )
    if decision.role == "fresh_challenges_baseline":
        return (
            f"同级新增探索对 {baseline.event_count} 条下级数据库信号形成反向挑战，"
            "但证据强度还不足以推翻原主线。"
            "本期应冻结置信度上调，并把反向证据列入下一周期验证。"
        )
    if decision.role == "fresh_leads_watch":
        return (
            "同级新增探索强于下级数据库沉淀，但连续性还不够。"
            f"本期应作为{scale_label}新增观察或潜在主线处理，"
            "除非后续出现官方公告、客户认证、财报或供应链一手证据。"
        )
    return (
        "下级数据库沉淀和同级新增探索都不足以支撑强判断。"
        "本期应降级为观察项或噪音，避免为丰富内容而堆叠信息。"
    )


def representative_fresh_evidence(fresh_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return CitationRanker().representative_fresh_evidence(fresh_evidence)


def rank_articles_for_theme(theme: str, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return CitationRanker().rank_articles_for_theme(theme, articles)


class CitationRanker:
    """Select representative fresh evidence citations for synthesis output."""

    def __init__(self, max_per_theme: int = 3):
        self.max_per_theme = max(1, int(max_per_theme))

    def representative_fresh_evidence(self, fresh_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for article in fresh_evidence:
            theme = fresh_article_theme(article)
            buckets.setdefault(theme, []).append(article)
        representatives = []
        for theme, articles in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
            representatives.extend(self.representative_articles_for_theme(theme, articles))
        return representatives

    def rank_articles_for_theme(self, theme: str, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored = [
            (fresh_article_score(theme, set(), set(), article), article)
            for article in articles
        ]
        scored.sort(key=lambda item: (-item[0], evidence_class_rank(item[1]), source_rank(item[1]), item[1].get("title", "")))
        return [article for _, article in scored]

    def representative_articles_for_theme(self, theme: str, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Select relevant, source-diverse, and counter-evidence-aware citations."""
        ranked = self.rank_articles_for_theme(theme, articles)
        selected: list[dict[str, Any]] = []

        def add(article: dict[str, Any]) -> None:
            if len(selected) < self.max_per_theme and article not in selected:
                selected.append(article)

        if ranked:
            add(ranked[0])

        counter = next((article for article in ranked if evidence_stance(article) == "counter"), None)
        if counter:
            add(counter)

        for article in ranked:
            if len(selected) >= self.max_per_theme:
                break
            if article in selected:
                continue
            if self._adds_source_diversity(article, selected):
                add(article)

        for article in ranked:
            if len(selected) >= self.max_per_theme:
                break
            add(article)

        return selected

    def _adds_source_diversity(self, article: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
        if not selected:
            return True
        selected_types = {str(item.get("source_type") or "") for item in selected}
        selected_sources = {source_identity(item) for item in selected}
        return (
            str(article.get("source_type") or "") not in selected_types
            or source_identity(article) not in selected_sources
        )


def fresh_article_theme(article: dict[str, Any]) -> str:
    text = fresh_article_text(article)
    ranked = []
    for theme in [
        "HBM 认证与产能",
        "中国存储扩张",
        "企业级存储与控制器",
        "先进封装与 3D 存储",
        "存储价格与周期",
    ]:
        hits = sum(1 for keyword in theme_keywords(theme) if keyword in text)
        if hits:
            ranked.append((hits, theme))
    if not ranked:
        return "其他待筛选证据"
    ranked.sort(reverse=True)
    return ranked[0][1]


def fresh_article_score(
    theme: str,
    event_terms: set[str],
    event_entities: set[str],
    article: dict[str, Any],
) -> int:
    text = fresh_article_text(article)
    article_terms = meaningful_tokens(json_list(article.get("term_ids")) + json_list(article.get("terms")))
    article_entities = meaningful_tokens(json_list(article.get("entity_ids")) + json_list(article.get("entities")))

    score = 0
    keyword_hits = sum(1 for keyword in theme_keywords(theme) if keyword in text)
    if keyword_hits:
        score += min(keyword_hits, 3)
    if event_terms.intersection(article_terms):
        score += min(len(event_terms.intersection(article_terms)), 2)
    if event_entities.intersection(article_entities):
        score += min(len(event_entities.intersection(article_entities)) * 2, 4)
    if article.get("query_dimension") == "thread_watch":
        score += 2
    if article.get("source_type") in {"official", "analyst"}:
        score += 1
    if fresh_article_theme(article) == theme:
        score += 2
    return score


def fresh_article_text(article: dict[str, Any]) -> str:
    fields = [
        article.get("title", ""),
        article.get("snippet", ""),
        article.get("extracted_summary", ""),
        article.get("query_id", ""),
        article.get("query_used", ""),
        article.get("query_dimension", ""),
        " ".join(str(value) for value in json_list(article.get("term_ids")) + json_list(article.get("terms"))),
        " ".join(str(value) for value in json_list(article.get("entity_ids")) + json_list(article.get("entities"))),
    ]
    return " ".join(fields).lower()


def evidence_stance(article: dict[str, Any]) -> str:
    """Classify whether a fresh article is supportive, counter, or neutral evidence."""
    text = fresh_article_text(article)
    counter_terms = [
        "delay", "delayed", "pushed back", "failed", "failure", "cut",
        "cuts", "reduced", "denied", "risk", "risks", "cancel", "cancelled",
        "challenge", "challenged", "contradict", "contradicts", "weaker",
        "missed", "shortfall", "推迟", "延迟", "未通过", "失败", "下调",
        "削减", "取消", "风险", "挑战", "反向", "不及预期",
    ]
    supportive_terms = [
        "approved", "qualified", "selected", "confirmed", "ramp", "increase",
        "growth", "expansion", "agreement", "order", "量产", "通过", "认证",
        "批准", "选定", "增长", "扩产", "上调", "协议", "订单",
    ]
    if any(term in text for term in counter_terms):
        return "counter"
    if any(term in text for term in supportive_terms):
        return "supportive"
    return "neutral"


def source_identity(article: dict[str, Any]) -> str:
    """Return a stable source key for citation diversity."""
    for key in ("source_domain", "source"):
        value = str(article.get(key) or "").strip().lower()
        if value:
            return value
    url = str(article.get("url") or "")
    if url:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        return host
    return ""


def theme_keywords(theme: str) -> list[str]:
    return {
        "存储价格与周期": ["dram", "nand", "price", "pricing", "shortage", "supply", "demand", "supercycle", "涨价", "价格", "供需", "缺口", "周期", "合约价", "现货"],
        "HBM 认证与产能": ["hbm", "hbm4", "hbm4e", "high bandwidth", "nvidia", "sk hynix", "samsung", "micron", "认证", "样品", "量产", "英伟达"],
        "中国存储扩张": ["cxmt", "ymtc", "changxin", "yangtze", "giga device", "长鑫", "长存", "长江存储", "兆易创新", "中国存储", "国产"],
        "先进封装与 3D 存储": ["advanced packaging", "3d nand", "3d flash", "soic", "emib", "cba", "hybrid bonding", "layer", "层", "先进封装", "堆叠", "键合"],
        "企业级存储与控制器": ["ssd", "nvme", "marvell", "controller", "enterprise", "data center", "ai inference", "hbf", "cxl", "控制器", "企业级", "数据中心"],
    }.get(theme, [])


def meaningful_tokens(values: list[Any]) -> set[str]:
    generic = {"", "ai", "memory", "storage", "semiconductor", "demand", "supply", "cloud", "data center", "存储", "内存", "半导体"}
    return {
        str(value).strip().lower()
        for value in values
        if str(value).strip().lower() not in generic
    }


def source_rank(article: dict[str, Any]) -> int:
    return {"official": 0, "financial": 1, "analyst": 2, "media": 3, "blog": 4}.get(article.get("source_type"), 5)


def evidence_class_rank(article: dict[str, Any]) -> int:
    return {
        "customer_commitment": 0,
        "financial_outcome": 1,
        "technical_validation": 2,
        "supply_capacity": 3,
        "counter_evidence": 4,
        "market_forecast": 5,
        "general": 6,
    }.get(classify_evidence_class(article), 9)


def json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [value]
        except json.JSONDecodeError:
            return [value]
    return [value]
