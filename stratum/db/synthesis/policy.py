"""Scale-independent synthesis policy for report evidence integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SynthesisPolicyConfig:
    """Tunable thresholds for scale-independent synthesis decisions."""

    strong_event_count: int = 3
    moderate_event_count: int = 2
    strong_date_count: int = 2
    strong_source_event_count: int = 3
    moderate_source_event_count: int = 2
    strong_fresh_count: int = 3
    moderate_fresh_count: int = 2
    strong_fresh_source_count: int = 2
    high_quality_source_types: frozenset[str] = frozenset({"official", "analyst"})
    positive_direction_terms: frozenset[str] = frozenset({
        "advance",
        "approved",
        "certified",
        "expand",
        "growth",
        "increase",
        "qualification",
        "ramp",
        "ship",
        "supply",
        "validate",
        "认证",
        "验证",
        "扩产",
        "出货",
        "增长",
        "上调",
        "推进",
        "通过",
        "量产",
    })
    negative_direction_terms: frozenset[str] = frozenset({
        "cancel",
        "cut",
        "delay",
        "deny",
        "failed",
        "pause",
        "pushed back",
        "reject",
        "shortage",
        "slip",
        "weaker",
        "下调",
        "取消",
        "否认",
        "失败",
        "延迟",
        "放缓",
        "推迟",
        "搁置",
        "未通过",
        "疲软",
    })


@dataclass(frozen=True)
class BaselineSignal:
    """Strength of accumulated lower-scale database state for one theme."""

    event_count: int
    date_count: int
    source_event_count: int
    strength: str
    direction: str = "mixed_or_unknown"


@dataclass(frozen=True)
class FreshAssessment:
    """Quality and role of same-scale exploring evidence for one theme."""

    evidence_count: int
    source_count: int
    high_quality_count: int
    quality: str
    direction: str = "mixed_or_unknown"
    evidence_class_counts: dict[str, int] = field(default_factory=dict)
    dominant_evidence_class: str = "general"


@dataclass(frozen=True)
class IntegrationDecision:
    """Decision for how a report should combine database memory and fresh evidence."""

    role: str
    confidence_effect: str
    direction: str = "mixed_or_unknown"
    conflict_level: str = "none"


@dataclass(frozen=True)
class SynthesisEvaluation:
    """Full policy output for one theme before rendering."""

    baseline: BaselineSignal
    fresh: FreshAssessment
    decision: IntegrationDecision

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable policy decision payload."""
        return asdict(self)


class SynthesisPolicy:
    """Composable policy object for higher-scale report synthesis."""

    def __init__(self, config: SynthesisPolicyConfig | None = None) -> None:
        self.config = config or SynthesisPolicyConfig()

    def evaluate(
        self,
        *,
        target_scale: str,
        events: list[dict[str, Any]],
        fresh_articles: list[dict[str, Any]],
    ) -> SynthesisEvaluation:
        """Run the full policy for one candidate theme."""
        baseline = self.assess_baseline(events)
        fresh = self.assess_fresh_evidence(fresh_articles)
        decision = self.decide_integration(
            target_scale=target_scale,
            baseline=baseline,
            fresh=fresh,
        )
        return SynthesisEvaluation(
            baseline=baseline,
            fresh=fresh,
            decision=decision,
        )

    def assess_baseline(self, events: list[dict[str, Any]]) -> BaselineSignal:
        """Assess whether lower-scale DB state is weak, moderate, or strong."""
        event_count = len(events)
        dates = {event.get("date") for event in events if event.get("date")}
        source_events = {
            source_event_id
            for event in events
            for source_event_id in _jsonish_list(event.get("source_event_ids"))
            if source_event_id
        }
        source_event_count = len(source_events) or event_count
        if (
            event_count >= self.config.strong_event_count
            or len(dates) >= self.config.strong_date_count
            or source_event_count >= self.config.strong_source_event_count
        ):
            strength = "strong"
        elif (
            event_count >= self.config.moderate_event_count
            or source_event_count >= self.config.moderate_source_event_count
        ):
            strength = "moderate"
        else:
            strength = "weak"
        return BaselineSignal(
            event_count=event_count,
            date_count=len(dates),
            source_event_count=source_event_count,
            strength=strength,
            direction=self._direction_for_records(events),
        )

    def assess_fresh_evidence(self, articles: list[dict[str, Any]]) -> FreshAssessment:
        """Assess whether same-scale fresh evidence is absent, weak, moderate, or strong."""
        sources = {
            article.get("source") or article.get("source_domain")
            for article in articles
            if article.get("source") or article.get("source_domain")
        }
        evidence_class_counts: dict[str, int] = {}
        for article in articles:
            evidence_class = classify_evidence_class(article)
            evidence_class_counts[evidence_class] = evidence_class_counts.get(evidence_class, 0) + 1
        high_value_classes = {"customer_commitment", "financial_outcome", "technical_validation", "supply_capacity"}
        high_quality_count = sum(
            1
            for article in articles
            if (
                article.get("source_type") in self.config.high_quality_source_types
                or classify_evidence_class(article) in high_value_classes
            )
        )
        if (
            len(articles) >= self.config.strong_fresh_count
            and (high_quality_count > 0 or len(sources) >= self.config.strong_fresh_source_count)
        ):
            quality = "strong"
        elif len(articles) >= self.config.moderate_fresh_count or len(sources) >= self.config.strong_fresh_source_count:
            quality = "moderate"
        elif articles:
            quality = "weak"
        else:
            quality = "absent"
        return FreshAssessment(
            evidence_count=len(articles),
            source_count=len(sources),
            high_quality_count=high_quality_count,
            quality=quality,
            direction=self._direction_for_records(articles),
            evidence_class_counts=evidence_class_counts,
            dominant_evidence_class=_dominant_evidence_class(evidence_class_counts),
        )

    def decide_integration(
        self,
        *,
        target_scale: str,
        baseline: BaselineSignal,
        fresh: FreshAssessment,
    ) -> IntegrationDecision:
        """Decide how fresh evidence should affect a scale-level report theme."""
        del target_scale
        if fresh.quality == "absent":
            return IntegrationDecision(
                role="baseline_only",
                confidence_effect="no_fresh_lift",
                direction=baseline.direction,
            )

        if self._directions_conflict(baseline.direction, fresh.direction):
            if fresh.quality == "strong":
                return IntegrationDecision(
                    role="fresh_contradicts_baseline",
                    confidence_effect="lower_or_split",
                    direction="conflict",
                    conflict_level="high",
                )
            return IntegrationDecision(
                role="fresh_challenges_baseline",
                confidence_effect="hold",
                direction="conflict",
                conflict_level="medium",
            )

        if baseline.strength in {"strong", "moderate"} and fresh.quality == "strong":
            return IntegrationDecision(
                role="baseline_confirmed_by_fresh",
                confidence_effect="raise",
                direction=fresh.direction if fresh.direction != "mixed_or_unknown" else baseline.direction,
            )

        if baseline.strength in {"strong", "moderate"}:
            return IntegrationDecision(
                role="baseline_supplemented_by_fresh",
                confidence_effect="slight_raise",
                direction=fresh.direction if fresh.direction != "mixed_or_unknown" else baseline.direction,
            )

        if fresh.quality == "strong":
            return IntegrationDecision(
                role="fresh_leads_watch",
                confidence_effect="watch_only",
                direction=fresh.direction,
            )

        return IntegrationDecision(
            role="insufficient",
            confidence_effect="none",
            direction="mixed_or_unknown",
        )

    def _direction_for_records(self, records: list[dict[str, Any]]) -> str:
        """Classify broad evidence direction without interpreting domain specifics."""
        directions = [self._direction_for_record(record) for record in records]
        positive_hits = sum(1 for direction in directions if direction == "positive_momentum")
        negative_hits = sum(1 for direction in directions if direction == "negative_momentum")
        if positive_hits and not negative_hits:
            return "positive_momentum"
        if negative_hits and not positive_hits:
            return "negative_momentum"
        if positive_hits and negative_hits:
            return "mixed_or_unknown"
        return "mixed_or_unknown"

    def _direction_for_record(self, record: dict[str, Any]) -> str:
        """Classify one record; negative reversal cues win inside the same record."""
        text = _record_text(record).lower()
        negative_hits = sum(1 for term in self.config.negative_direction_terms if term in text)
        if negative_hits:
            return "negative_momentum"
        positive_hits = sum(1 for term in self.config.positive_direction_terms if term in text)
        if positive_hits:
            return "positive_momentum"
        return "mixed_or_unknown"

    @staticmethod
    def _directions_conflict(baseline_direction: str, fresh_direction: str) -> bool:
        return {baseline_direction, fresh_direction} == {"positive_momentum", "negative_momentum"}


DEFAULT_POLICY = SynthesisPolicy()
SCALE_POLICY_CONFIGS: dict[str, SynthesisPolicyConfig] = {
    "weekly": SynthesisPolicyConfig(),
    "monthly": SynthesisPolicyConfig(
        strong_event_count=4,
        moderate_event_count=3,
        strong_date_count=3,
        strong_source_event_count=4,
        moderate_source_event_count=3,
    ),
    "quarterly": SynthesisPolicyConfig(
        strong_event_count=5,
        moderate_event_count=4,
        strong_date_count=3,
        strong_source_event_count=5,
        moderate_source_event_count=4,
        strong_fresh_count=4,
    ),
    "yearly": SynthesisPolicyConfig(
        strong_event_count=6,
        moderate_event_count=5,
        strong_date_count=4,
        strong_source_event_count=6,
        moderate_source_event_count=5,
        strong_fresh_count=4,
        strong_fresh_source_count=3,
    ),
}


def get_synthesis_policy_config(target_scale: str) -> SynthesisPolicyConfig:
    """Return the configured synthesis thresholds for one report scale."""
    return SCALE_POLICY_CONFIGS.get(target_scale, SCALE_POLICY_CONFIGS["weekly"])


def get_synthesis_policy(target_scale: str) -> SynthesisPolicy:
    """Return a synthesis policy instance for one report scale."""
    return SynthesisPolicy(get_synthesis_policy_config(target_scale))


def evaluate_theme(
    *,
    target_scale: str,
    events: list[dict[str, Any]],
    fresh_articles: list[dict[str, Any]],
    policy: SynthesisPolicy | None = None,
) -> SynthesisEvaluation:
    """Evaluate one candidate theme with the configured synthesis policy."""
    active_policy = policy or get_synthesis_policy(target_scale)
    return active_policy.evaluate(
        target_scale=target_scale,
        events=events,
        fresh_articles=fresh_articles,
    )


def assess_baseline(events: list[dict[str, Any]]) -> BaselineSignal:
    """Compatibility wrapper for the default policy."""
    return DEFAULT_POLICY.assess_baseline(events)


def assess_fresh_evidence(articles: list[dict[str, Any]]) -> FreshAssessment:
    """Compatibility wrapper for the default policy."""
    return DEFAULT_POLICY.assess_fresh_evidence(articles)


def decide_integration(
    *,
    target_scale: str,
    baseline: BaselineSignal,
    fresh: FreshAssessment,
) -> IntegrationDecision:
    """Compatibility wrapper for the default policy."""
    return DEFAULT_POLICY.decide_integration(
        target_scale=target_scale,
        baseline=baseline,
        fresh=fresh,
    )


def classify_evidence_class(record: dict[str, Any]) -> str:
    """Classify evidence into a calibration bucket for synthesis decisions."""
    text = _record_text(record).lower()
    source_type = str(record.get("source_type") or record.get("source_type_hint") or "").lower()
    if any(term in text for term in ("delay", "failed", "cut", "risk", "推迟", "失败", "下调", "风险")):
        return "counter_evidence"
    if any(term in text for term in ("design win", "selected", "order", "commitment", "supply agreement", "定点", "订单", "供应协议")):
        return "customer_commitment"
    if source_type == "financial" or any(term in text for term in ("earnings", "revenue", "margin", "capex", "财报", "营收", "利润", "资本开支")):
        return "financial_outcome"
    if any(term in text for term in ("qualification", "certification", "validation", "sample", "认证", "验证", "样品")):
        return "technical_validation"
    if any(term in text for term in ("capacity", "supply", "shipment", "ramp", "yield", "产能", "供应", "出货", "良率", "扩产")):
        return "supply_capacity"
    if any(term in text for term in ("forecast", "guidance", "expects", "may", "预计", "指引", "可能")):
        return "market_forecast"
    return "general"


def _dominant_evidence_class(counts: dict[str, int]) -> str:
    if not counts:
        return "general"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _jsonish_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def _record_text(record: dict[str, Any]) -> str:
    fields = [
        record.get("title", ""),
        record.get("snippet", ""),
        record.get("summary", ""),
        record.get("extracted_summary", ""),
        record.get("body", ""),
        " ".join(str(value) for value in _jsonish_list(record.get("terms"))),
        " ".join(str(value) for value in _jsonish_list(record.get("term_ids"))),
        " ".join(str(value) for value in _jsonish_list(record.get("entities"))),
        " ".join(str(value) for value in _jsonish_list(record.get("entity_ids"))),
    ]
    return " ".join(str(field) for field in fields if field)
