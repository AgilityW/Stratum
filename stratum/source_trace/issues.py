"""SourceTrace issue mining from analyzer outputs."""

from __future__ import annotations

from typing import Any


def mine_issues(
    *,
    observation_health: dict[str, Any],
    funnel: dict[str, Any],
    missed_signals: list[dict[str, Any]],
    provenance: dict[str, Any],
    quality: list[dict[str, Any]],
    input_errors: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Detect actionable source, parser, policy, and provenance issues."""
    issues = []
    if input_errors:
        issues.extend(_input_error_issues(input_errors))
    issues.extend(_observation_issues(observation_health))
    issues.extend(_funnel_issues(funnel))
    issues.extend(_quality_issues(quality))
    if missed_signals:
        issues.append({
            "scope": "admission",
            "severity": "high",
            "code": "missed_signals",
            "message": f"{len(missed_signals)} rejected or unjudged signals matched later records",
        })
    deduped = provenance.get("totals", {}).get("deduped_paths", 0)
    if deduped:
        issues.append({
            "scope": "provenance",
            "severity": "medium",
            "code": "multi_path_dedupe",
            "message": f"{deduped} acquisition paths were collapsed by canonical URL dedupe",
        })
    return {
        "issues": sorted(issues, key=lambda item: (_severity_rank(item["severity"]), item["scope"], item["code"])),
        "totals": {
            "issues": len(issues),
            "high": sum(1 for item in issues if item["severity"] == "high"),
            "medium": sum(1 for item in issues if item["severity"] == "medium"),
            "low": sum(1 for item in issues if item["severity"] == "low"),
        },
    }


def _observation_issues(observation_health: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    for layer in ("watchlist", "discovery"):
        for row in observation_health.get(layer, {}).get("sources", []):
            status = row.get("health_status")
            if status in {"needs_adapter_review", "date_poor", "duplicate_heavy"}:
                issues.append({
                    "scope": layer,
                    "source": row.get("source", ""),
                    "severity": "high" if status == "needs_adapter_review" else "medium",
                    "code": status,
                    "message": f"{row.get('source')} observation health is {status}",
                })
    return issues


def _input_error_issues(input_errors: dict[str, int]) -> list[dict[str, Any]]:
    issues = []
    for layer, count in sorted(input_errors.items()):
        if count <= 0:
            continue
        issues.append({
            "scope": "input",
            "source": layer,
            "severity": "high" if count >= 5 else "medium",
            "code": "malformed_input_rows",
            "message": f"{layer} dropped {count} malformed input rows during SourceTrace load",
        })
    return issues


def _funnel_issues(funnel: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    for row in funnel.get("sources", []):
        if row.get("seen", 0) >= 5 and row.get("admitted", 0) == 0:
            issues.append({
                "scope": "source",
                "source": row.get("source", ""),
                "severity": "medium",
                "code": "all_candidates_rejected",
                "message": f"{row.get('source')} has observations/candidates but no admitted results",
            })
    return issues


def _quality_issues(quality: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "scope": "source",
            "source": row.get("source", ""),
            "severity": "low",
            "code": "low_quality_source",
            "message": f"{row.get('source')} is currently scored as noisy",
        }
        for row in quality
        if row.get("tier") == "noisy"
    ]


def _severity_rank(severity: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)
