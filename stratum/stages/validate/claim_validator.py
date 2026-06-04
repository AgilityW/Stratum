"""Claim support and overclaim validation algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class EvidenceClassRule:
    """Rule describing when a claim needs stronger supporting evidence."""

    name: str
    claim_patterns: tuple[str, ...]
    weak_evidence_patterns: tuple[str, ...] = ()
    support_patterns: tuple[str, ...] = ()
    weak_source_types: frozenset[str] = field(default_factory=frozenset)


OVERCLAIM_RULES = (
    EvidenceClassRule(
        name="sample_or_qualification_overstated_as_mass_production",
        claim_patterns=(
            r"confirmed mass production",
            r"\bmass production\b",
            r"已确认量产",
            r"确认量产",
            r"进入量产",
            r"实质性量产",
        ),
        weak_evidence_patterns=(
            r"\bsample(?:s)?\b",
            r"\bqualification\b",
            r"\bcertification\b",
            r"\bvalidation\b",
            r"样品",
            r"认证",
            r"验证",
        ),
        support_patterns=(
            r"\bmass production\b",
            r"量产",
        ),
    ),
    EvidenceClassRule(
        name="reported_signal_overstated_as_confirmed",
        claim_patterns=(
            r"\bconfirmed\b",
            r"\bwill definitely\b",
            r"确定",
            r"已经确认",
        ),
        weak_evidence_patterns=(
            r"\breportedly\b",
            r"\brumou?rs?\b",
            r"\bsources said\b",
            r"据悉",
            r"传闻",
            r"消息称",
        ),
        support_patterns=(
            r"\bconfirmed\b",
            r"\bofficially\b",
            r"官方",
            r"确认",
        ),
    ),
    EvidenceClassRule(
        name="forecast_overstated_as_certain_outcome",
        claim_patterns=(
            r"\bwill definitely\b",
            r"\bguaranteed\b",
            r"\bis certain to\b",
            r"必将",
            r"确定会",
            r"一定会",
        ),
        weak_evidence_patterns=(
            r"\bexpects?\b",
            r"\bforecast(?:s|ed)?\b",
            r"\bguidance\b",
            r"\bmay\b",
            r"\bcould\b",
            r"\blikely\b",
            r"预计",
            r"可能",
            r"展望",
            r"指引",
        ),
        support_patterns=(
            r"\bwill definitely\b",
            r"\bguaranteed\b",
            r"\bis certain to\b",
            r"必将",
            r"确定会",
            r"一定会",
        ),
    ),
    EvidenceClassRule(
        name="customer_commitment_requires_confirmed_customer_evidence",
        claim_patterns=(
            r"\bcustomer (?:win|award|order|commitment)\b",
            r"\bdesign win\b",
            r"\bselected by\b",
            r"\bapproved by\b",
            r"\bqualified by\b",
            r"\bNVIDIA (?:approved|selected|qualified)\b",
            r"客户订单",
            r"客户已批准",
            r"客户已认证",
            r"设计定点",
            r"供应协议",
        ),
        weak_evidence_patterns=(
            r"\bqualification\b",
            r"\bvalidation\b",
            r"\bevaluation\b",
            r"\bsample(?:s)?\b",
            r"\btrial(?:s)?\b",
            r"\breportedly\b",
            r"\bsources said\b",
            r"认证中",
            r"验证中",
            r"样品",
            r"据悉",
            r"消息称",
        ),
        support_patterns=(
            r"\bcustomer announced\b",
            r"\bcustomer said\b",
            r"\bNVIDIA said\b",
            r"\bapproved\b",
            r"\bqualified\b",
            r"\bselected\b",
            r"\bdesign win\b",
            r"\bsupply agreement\b",
            r"\bpurchase order\b",
            r"客户宣布",
            r"客户表示",
            r"已批准",
            r"已认证",
            r"已选定",
            r"供应协议",
        ),
        weak_source_types=frozenset({"analyst", "media", "blog", "social"}),
    ),
    EvidenceClassRule(
        name="financial_outcome_requires_financial_or_company_evidence",
        claim_patterns=(
            r"\brevenue (?:rose|grew|increased|will rise|will grow|will increase)\b",
            r"\bsales (?:rose|grew|increased|will rise|will grow|will increase)\b",
            r"\bmargin (?:expanded|will expand|improved|will improve)\b",
            r"\bprofit (?:rose|grew|increased|will rise|will grow|will increase)\b",
            r"\bASP(?:s)? (?:rose|will rise|increased|will increase)\b",
            r"\bcapex (?:rose|fell|increased|declined|will rise|will fall|will increase)\b",
            r"营收(?:增长|上升|将增长|将上升)",
            r"销售额(?:增长|上升|将增长|将上升)",
            r"利润(?:增长|上升|将增长|将上升)",
            r"毛利率(?:改善|扩张|将改善|将扩张)",
            r"资本开支(?:增加|下降|将增加|将下降)",
        ),
        weak_evidence_patterns=(
            r"\banalyst(?:s)? (?:estimate|expect|forecast|project)",
            r"\bchannel checks?\b",
            r"\bsupply chain sources\b",
            r"\bexpects?\b",
            r"\bforecast(?:s|ed)?\b",
            r"\bcould\b",
            r"\bmay\b",
            r"\blikely\b",
            r"分析师(?:预计|预测)",
            r"渠道调研",
            r"供应链消息",
            r"预计",
            r"可能",
        ),
        support_patterns=(
            r"\bearnings release\b",
            r"\bearnings call\b",
            r"\bfinancial statement\b",
            r"\bSEC filing\b",
            r"\b10-[QK]\b",
            r"\bcompany (?:said|reported|guided)\b",
            r"\bofficial filing\b",
            r"财报",
            r"业绩会",
            r"业绩指引",
            r"公司(?:表示|披露|公告)",
            r"证券交易所公告",
        ),
        weak_source_types=frozenset({"analyst", "media", "blog", "social"}),
    ),
    EvidenceClassRule(
        name="causal_language_requires_explicit_mechanism_evidence",
        claim_patterns=(
            r"\bcaused\b",
            r"\btriggered\b",
            r"\bled to\b",
            r"\bresulted in\b",
            r"\bdriven by\b",
            r"\bdue to\b",
            r"\bbecause of\b",
            r"导致",
            r"推动",
            r"驱动",
            r"由于",
            r"源于",
        ),
        weak_evidence_patterns=(
            r"\bmay (?:cause|drive|lead to|result in)\b",
            r"\bcould (?:cause|drive|lead to|result in)\b",
            r"\bmight (?:cause|drive|lead to|result in)\b",
            r"\bcorrelat(?:e|es|ed|ion)\b",
            r"\bcoincid(?:e|es|ed|ing)\b",
            r"\blink(?:ed|s)? to\b",
            r"\banalysts? (?:expect|estimate|suggest)\b",
            r"可能(?:导致|推动|驱动)",
            r"相关",
            r"同步出现",
            r"分析师(?:预计|认为)",
        ),
        support_patterns=(
            r"\bresulted from\b",
            r"\bwas caused by\b",
            r"\bwere caused by\b",
            r"\bwas driven by\b",
            r"\bwere driven by\b",
            r"\battributed .* to\b",
            r"\bciting .* as the reason\b",
            r"\bcompany said .* because\b",
            r"\bmanagement said .* because\b",
            r"原因是",
            r"归因于",
            r"公司表示.*由于",
            r"管理层表示.*由于",
        ),
    ),
)


class ClaimValidator:
    """Validate whether generated claims overstate their evidence class."""

    def __init__(self, overclaim_rules: list[dict | EvidenceClassRule] | None = None):
        self.overclaim_rules = tuple(
            _normalize_rule(rule)
            for rule in (overclaim_rules if overclaim_rules is not None else OVERCLAIM_RULES)
        )

    def validate_overclaims(self, item: dict, supporting_articles: list[dict]) -> list[str]:
        """Flag generated claims that overstate supporting evidence."""
        if not supporting_articles:
            return []
        claim_text = f"{item.get('title', '')} {' '.join(item.get('body', []))}".lower()
        claim_entities = claim_entity_tokens(claim_text)
        violations = []
        for rule in self.overclaim_rules:
            if not _matches_any(claim_text, rule.claim_patterns):
                continue
            weak_articles = [
                article.get("id") or article.get("title") or "unknown"
                for article in supporting_articles
                if self._article_is_weaker_than_claim(article, rule, claim_entities)
            ]
            if weak_articles:
                violations.append(
                    f"OVERCLAIM: {rule.name} in item '{item.get('title', '')[:60]}'; "
                    f"supporting evidence is weaker than the claim: {weak_articles[:5]}."
                )
        return violations

    def _article_is_weaker_than_claim(
        self,
        article: dict,
        rule: EvidenceClassRule,
        claim_entities: set[str],
    ) -> bool:
        evidence_text = article_evidence_text(article)
        if claim_entities and not claim_entities.intersection(claim_entity_tokens(evidence_text)):
            return True
        if _matches_any(evidence_text, rule.support_patterns):
            return False
        if _matches_any(evidence_text, rule.weak_evidence_patterns):
            return True
        return article_source_type(article) in rule.weak_source_types


def validate_overclaims(item: dict, supporting_articles: list[dict]) -> list[str]:
    """Compatibility wrapper for existing validate-stage callers."""
    return ClaimValidator().validate_overclaims(item, supporting_articles)


def article_evidence_text(article: dict) -> str:
    fields = [
        article.get("title", ""),
        article.get("snippet", ""),
        article.get("description", ""),
        article.get("extracted_summary", ""),
    ]
    return " ".join(str(field) for field in fields).lower()


def article_source_type(article: dict) -> str:
    raw_metadata = article.get("raw_metadata") or {}
    return str(
        article.get("source_type")
        or article.get("source_type_hint")
        or raw_metadata.get("source_type")
        or raw_metadata.get("source_type_hint")
        or ""
    ).strip().lower()


def claim_entity_tokens(text: str) -> set[str]:
    """Return high-salience entity tokens that should appear in support evidence."""
    entity_aliases = {
        "nvidia": ("nvidia", "英伟达"),
        "samsung": ("samsung", "三星"),
        "sk hynix": ("sk hynix", "sk海力士", "海力士"),
        "micron": ("micron", "美光"),
        "cxmt": ("cxmt", "长鑫"),
        "ymtc": ("ymtc", "长江存储", "长存"),
    }
    lowered = text.lower()
    return {
        canonical
        for canonical, aliases in entity_aliases.items()
        if any(alias in lowered for alias in aliases)
    }


def _normalize_rule(rule: dict | EvidenceClassRule) -> EvidenceClassRule:
    if isinstance(rule, EvidenceClassRule):
        return rule
    return EvidenceClassRule(
        name=rule["name"],
        claim_patterns=tuple(rule.get("claim_patterns", ())),
        weak_evidence_patterns=tuple(rule.get("weak_evidence_patterns", ())),
        support_patterns=tuple(rule.get("support_patterns", ())),
        weak_source_types=frozenset(
            str(source_type).strip().lower()
            for source_type in rule.get("weak_source_types", ())
            if str(source_type).strip()
        ),
    )


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)
