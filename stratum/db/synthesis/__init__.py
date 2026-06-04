"""DB-native synthesis package.

The package keeps DB-native weekly/monthly/quarterly/yearly synthesis behind a
stable import surface while its engine, payload helpers, and algorithm
components live in separate modules.
"""

from stratum.db.synthesis.engine import (
    SUPPORTED_TARGET_SCALES,
    synthesize_cascade_report,
    _article_display_title,
    _article_focus_terms,
    _article_titles,
    _build_report_payload,
    _build_synthesized_events,
    _display_hypothesis,
    _event_points,
    _event_sort_key,
    _executive_summary_conclusions,
    _fresh_coverage_body,
    _fresh_coverage_title,
    _fresh_evidence_body,
    _fresh_evidence_title,
    _group_events_by_thread,
    _integration_decision_text,
    _is_chinese_display_text,
    _judgment_body,
    _lead_event,
    _lead_event_for_theme,
    _lineage_body,
    _lowest_confidence,
    _matching_fresh_evidence,
    _numbered_lines,
    _rank_thread_groups,
    _report_topic_key,
    _signal_noise_body,
    _slug,
    _summary_body,
    _summary_title,
    _synthesis_title,
    _theme_body,
    _thread_theme,
    _trend_body,
    _unique_flatten,
    _unique_judgments,
    _watchlist_body,
)
from stratum.db.synthesis.evidence import CitationRanker
from stratum.db.synthesis.events import SynthesizedEventBuilder
from stratum.db.synthesis.judgment_feedback import JudgmentFeedback, JudgmentFeedbackScorer
from stratum.db.synthesis.payload import build_report_payload
from stratum.db.synthesis.policy import (
    BaselineSignal,
    FreshAssessment,
    IntegrationDecision,
    SynthesisEvaluation,
    SynthesisPolicy,
    SynthesisPolicyConfig,
    assess_baseline,
    assess_fresh_evidence,
    classify_evidence_class,
    decide_integration,
    evaluate_theme,
    get_synthesis_policy,
    get_synthesis_policy_config,
)
from stratum.db.synthesis.ranker import ThemeRanker
from stratum.db.synthesis.text import SynthesisTextBuilder

__all__ = [
    "BaselineSignal",
    "CitationRanker",
    "FreshAssessment",
    "IntegrationDecision",
    "JudgmentFeedback",
    "JudgmentFeedbackScorer",
    "SUPPORTED_TARGET_SCALES",
    "SynthesisEvaluation",
    "SynthesisPolicy",
    "SynthesisPolicyConfig",
    "SynthesisTextBuilder",
    "SynthesizedEventBuilder",
    "ThemeRanker",
    "assess_baseline",
    "assess_fresh_evidence",
    "classify_evidence_class",
    "build_report_payload",
    "decide_integration",
    "evaluate_theme",
    "get_synthesis_policy",
    "get_synthesis_policy_config",
    "synthesize_cascade_report",
]
