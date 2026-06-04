"""Deterministic report evaluation helpers.

The harness is intentionally model-free. It gives algorithm work a stable
regression target before any reviewer or LLM-based scoring layer is added.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvaluationCase:
    """One fixed report-quality benchmark case."""

    case_id: str
    scale: str
    domain: str
    report_markdown: str
    expectations: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationCase":
        return cls(
            case_id=str(payload["id"]),
            scale=str(payload.get("scale", "")),
            domain=str(payload.get("domain", "")),
            report_markdown=str(payload.get("report_markdown", "")),
            expectations=dict(payload.get("expectations") or {}),
        )


@dataclass(frozen=True)
class EvaluationCheck:
    """One scored quality check for a case."""

    name: str
    passed: bool
    score: float
    expected: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": round(self.score, 3),
            "expected": list(self.expected),
            "matched": list(self.matched),
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class EvaluationResult:
    """Evaluation output for one benchmark case."""

    case_id: str
    scale: str
    domain: str
    passed: bool
    score: float
    checks: list[EvaluationCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scale": self.scale,
            "domain": self.domain,
            "passed": self.passed,
            "score": round(self.score, 3),
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class EvaluationSummary:
    """Aggregate output for a benchmark run."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    average_score: float
    metrics: dict[str, float]
    results: list[EvaluationResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "average_score": round(self.average_score, 3),
            "metrics": {key: round(value, 3) for key, value in sorted(self.metrics.items())},
            "results": [result.to_dict() for result in self.results],
        }


def load_cases(path: str | Path) -> list[EvaluationCase]:
    payload = json.loads(Path(path).read_text())
    case_payloads = payload.get("cases", payload if isinstance(payload, list) else [])
    return [EvaluationCase.from_dict(item) for item in case_payloads]


def evaluate_cases(cases: list[EvaluationCase]) -> EvaluationSummary:
    results = [evaluate_case(case) for case in cases]
    passed = sum(1 for result in results if result.passed)
    average = sum(result.score for result in results) / len(results) if results else 0.0
    return EvaluationSummary(
        total_cases=len(results),
        passed_cases=passed,
        failed_cases=len(results) - passed,
        average_score=average,
        metrics=_metric_suite(results),
        results=results,
    )


def evaluate_case(case: EvaluationCase) -> EvaluationResult:
    text = case.report_markdown.casefold()
    expectations = case.expectations
    checks = [
        _contains_all_check("required_phrases", text, expectations.get("required_phrases", [])),
        _contains_all_check("required_sources", text, expectations.get("required_sources", [])),
        _contains_all_check("traceability_terms", text, expectations.get("traceability_terms", [])),
        _contains_any_check("citation_markers", text, expectations.get("citation_markers", [])),
        _contains_any_check("judgment_signals", text, expectations.get("judgment_signals", [])),
        _contains_any_check("executive_implications", text, expectations.get("executive_implications", [])),
        _contains_any_check("confidence_terms", text, expectations.get("confidence_terms", [])),
        _contains_none_check("prohibited_phrases", text, expectations.get("prohibited_phrases", [])),
    ]
    active_checks = [check for check in checks if check.expected]
    score = (
        sum(check.score for check in active_checks) / len(active_checks)
        if active_checks
        else 1.0
    )
    min_score = float(expectations.get("min_score", 1.0))
    passed = all(check.passed for check in active_checks) and score >= min_score
    return EvaluationResult(
        case_id=case.case_id,
        scale=case.scale,
        domain=case.domain,
        passed=passed,
        score=score,
        checks=checks,
    )


def _contains_all_check(name: str, text: str, expected: list[str]) -> EvaluationCheck:
    normalized = _normalize_expected(expected)
    matched = [item for item in normalized if item.casefold() in text]
    missing = [item for item in normalized if item not in matched]
    score = len(matched) / len(normalized) if normalized else 1.0
    return EvaluationCheck(
        name=name,
        passed=not missing,
        score=score,
        expected=normalized,
        matched=matched,
        missing=missing,
    )


def _contains_any_check(name: str, text: str, expected: list[str]) -> EvaluationCheck:
    normalized = _normalize_expected(expected)
    matched = [item for item in normalized if item.casefold() in text]
    passed = bool(matched) if normalized else True
    return EvaluationCheck(
        name=name,
        passed=passed,
        score=1.0 if passed else 0.0,
        expected=normalized,
        matched=matched,
        missing=[] if passed else normalized,
    )


def _contains_none_check(name: str, text: str, expected: list[str]) -> EvaluationCheck:
    normalized = _normalize_expected(expected)
    matched = [item for item in normalized if item.casefold() in text]
    return EvaluationCheck(
        name=name,
        passed=not matched,
        score=0.0 if matched else 1.0,
        expected=normalized,
        matched=matched,
        missing=[],
    )


def _normalize_expected(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        return [values]
    return [str(value) for value in values if str(value).strip()]


def _metric_suite(results: list[EvaluationResult]) -> dict[str, float]:
    """Aggregate check-level scores for regression gates."""
    grouped: dict[str, list[float]] = {}
    for result in results:
        for check in result.checks:
            if not check.expected:
                continue
            grouped.setdefault(check.name, []).append(check.score)
    return {
        name: sum(scores) / len(scores)
        for name, scores in grouped.items()
        if scores
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate fixed report-quality benchmark cases.")
    parser.add_argument("--cases", required=True, help="Path to evaluation cases JSON.")
    parser.add_argument("--output", help="Optional path for JSON summary output.")
    args = parser.parse_args(argv)

    summary = evaluate_cases(load_cases(args.cases))
    output = json.dumps(summary.to_dict(), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output + "\n")
    else:
        print(output)
    return 0 if summary.failed_cases == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
