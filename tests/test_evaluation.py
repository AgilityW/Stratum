from pathlib import Path

from stratum.evaluation import EvaluationCase, evaluate_case, evaluate_cases, load_cases


FIXTURE = Path(__file__).parent / "fixtures" / "evaluation" / "report_cases.json"


def test_evaluation_harness_passes_fixed_report_case():
    cases = load_cases(FIXTURE)
    summary = evaluate_cases(cases)

    assert summary.total_cases == 3
    assert summary.passed_cases == 3
    assert summary.failed_cases == 0
    assert summary.results[0].score == 1.0
    assert summary.metrics["traceability_terms"] == 1.0
    assert summary.metrics["executive_implications"] == 1.0
    assert summary.to_dict()["results"][0]["checks"][0]["name"] == "required_phrases"
    assert "metrics" in summary.to_dict()


def test_evaluation_harness_flags_missing_judgment_and_overclaim():
    case = EvaluationCase(
        case_id="weak-weekly",
        scale="weekly",
        domain="storage",
        report_markdown=(
            "Samsung announced HBM. This is confirmed mass production and a guaranteed winner."
        ),
        expectations={
            "required_phrases": ["HBM", "platform allocation"],
            "judgment_signals": ["indicates"],
            "traceability_terms": ["Evidence:", "source:"],
            "citation_markers": ["reuters.com"],
            "executive_implications": ["allocation risk"],
            "confidence_terms": ["until"],
            "prohibited_phrases": ["confirmed mass production", "guaranteed winner"],
            "min_score": 1.0,
        },
    )

    result = evaluate_case(case)

    assert not result.passed
    checks = {check.name: check for check in result.checks}
    assert checks["required_phrases"].missing == ["platform allocation"]
    assert checks["traceability_terms"].missing == ["Evidence:", "source:"]
    assert not checks["citation_markers"].passed
    assert not checks["executive_implications"].passed
    assert not checks["confidence_terms"].passed
    assert not checks["judgment_signals"].passed
    assert checks["prohibited_phrases"].matched == [
        "confirmed mass production",
        "guaranteed winner",
    ]
