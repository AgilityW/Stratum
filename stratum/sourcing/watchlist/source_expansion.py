"""Source expansion recommendations from the watchlist evidence funnel."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stratum.contracts.pipeline_artifacts import (
    RAW_RESULTS,
    WATCHLIST_CANDIDATES,
    WATCHLIST_OBSERVATIONS,
    WATCHLIST_RESULTS,
)


PROMOTE_MIN_OBSERVATIONS = 5
PROMOTE_MIN_RESULTS = 3
PROMOTE_RESULT_RATE = 0.5
PROMOTE_RAW_RATE = 0.4
DEPRIORITIZE_MIN_CANDIDATES = 5
DEPRIORITIZE_REJECT_RATE = 0.75
LOW_DATED_RATE = 0.5


@dataclass
class SourceFunnel:
    """Counters for one source across watchlist sidecar layers."""

    source: str
    access: str = ""
    observations: int = 0
    candidates: int = 0
    accepted_candidates: int = 0
    rejected_candidates: int = 0
    results: int = 0
    raw_selected: int = 0
    dated_results: int = 0
    locales: set[str] = field(default_factory=set)
    source_domains: set[str] = field(default_factory=set)
    source_type_hints: set[str] = field(default_factory=set)

    def observe(self, row: dict[str, Any]) -> None:
        self.observations += 1
        self._merge_identity(row)

    def candidate(self, row: dict[str, Any]) -> None:
        self.candidates += 1
        if bool(row.get("accepted")):
            self.accepted_candidates += 1
        else:
            self.rejected_candidates += 1
        self._merge_identity(row)

    def result(self, row: dict[str, Any]) -> None:
        self.results += 1
        if row.get("published_at"):
            self.dated_results += 1
        self._merge_identity(row)

    def selected(self, row: dict[str, Any]) -> None:
        self.raw_selected += 1
        self._merge_identity(row)

    def _merge_identity(self, row: dict[str, Any]) -> None:
        if not self.access and row.get("access"):
            self.access = str(row.get("access") or "")
        if row.get("locale"):
            self.locales.add(str(row["locale"]))
        if row.get("source_domain"):
            self.source_domains.add(str(row["source_domain"]))
        if row.get("source_type_hint"):
            self.source_type_hints.add(str(row["source_type_hint"]))

    def to_report(self) -> dict[str, Any]:
        observation_to_candidate_rate = _rate(self.candidates, self.observations)
        acceptance_rate = _rate(self.accepted_candidates, self.candidates)
        reject_rate = _rate(self.rejected_candidates, self.candidates)
        result_rate = _rate(self.results, self.observations)
        raw_selected_rate = _rate(self.raw_selected, self.results)
        dated_rate = _rate(self.dated_results, self.results)
        action, reasons, next_steps = _recommend_action(
            observations=self.observations,
            candidates=self.candidates,
            results=self.results,
            raw_selected=self.raw_selected,
            observation_to_candidate_rate=observation_to_candidate_rate,
            reject_rate=reject_rate,
            result_rate=result_rate,
            raw_selected_rate=raw_selected_rate,
            dated_rate=dated_rate,
        )
        return {
            "source": self.source,
            "access": self.access,
            "metrics": {
                "observations": self.observations,
                "candidates": self.candidates,
                "accepted_candidates": self.accepted_candidates,
                "rejected_candidates": self.rejected_candidates,
                "results": self.results,
                "raw_selected": self.raw_selected,
                "dated_results": self.dated_results,
                "observation_to_candidate_rate": observation_to_candidate_rate,
                "acceptance_rate": acceptance_rate,
                "reject_rate": reject_rate,
                "result_rate": result_rate,
                "raw_selected_rate": raw_selected_rate,
                "dated_rate": dated_rate,
            },
            "profile": {
                "locales": sorted(self.locales),
                "source_domains": sorted(self.source_domains),
                "source_type_hints": sorted(self.source_type_hints),
            },
            "recommendation": {
                "action": action,
                "reasons": reasons,
                "next_steps": next_steps,
            },
        }


def evaluate_source_expansion(run_data_dir: str) -> dict[str, Any]:
    """Evaluate source expansion signals from one run data directory."""
    funnels: dict[str, SourceFunnel] = {}

    for row in _read_jsonl(os.path.join(run_data_dir, WATCHLIST_OBSERVATIONS.filename)):
        _funnel(funnels, row).observe(row)

    for row in _read_jsonl(os.path.join(run_data_dir, WATCHLIST_CANDIDATES.filename)):
        _funnel(funnels, row).candidate(row)

    for row in _read_json(os.path.join(run_data_dir, WATCHLIST_RESULTS.filename), default=[]):
        if isinstance(row, dict):
            _funnel(funnels, row).result(row)

    for row in _read_json(os.path.join(run_data_dir, RAW_RESULTS.filename), default=[]):
        if isinstance(row, dict) and _is_watchlist_row(row):
            _funnel(funnels, row).selected(row)

    sources = [funnel.to_report() for funnel in funnels.values()]
    sources.sort(
        key=lambda row: (
            _action_rank(row["recommendation"]["action"]),
            -row["metrics"]["raw_selected"],
            -row["metrics"]["results"],
            row["source"],
        )
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_data_dir": run_data_dir,
        "artifact_chain": [
            WATCHLIST_OBSERVATIONS.filename,
            WATCHLIST_CANDIDATES.filename,
            WATCHLIST_RESULTS.filename,
            RAW_RESULTS.filename,
        ],
        "totals": _totals(sources),
        "sources": sources,
    }


def write_source_expansion_report(run_data_dir: str, output_path: str) -> str:
    """Write source expansion recommendations to an explicitly requested path."""
    report = evaluate_source_expansion(run_data_dir)
    with open(output_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return output_path


def _funnel(funnels: dict[str, SourceFunnel], row: dict[str, Any]) -> SourceFunnel:
    source = _source_id(row)
    if source not in funnels:
        funnels[source] = SourceFunnel(source=source, access=str(row.get("access") or ""))
    return funnels[source]


def _source_id(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "")
    if source:
        return source
    engine = str(row.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    query_id = str(row.get("query_id") or "")
    for prefix in ("df-", "rss-", "b-"):
        if query_id.startswith(prefix):
            query_id = query_id[len(prefix):]
            break
    for suffix in ("-fallback", "-list"):
        if query_id.endswith(suffix):
            query_id = query_id[: -len(suffix)]
    return query_id or "unknown"


def _is_watchlist_row(row: dict[str, Any]) -> bool:
    engine = str(row.get("engine") or "")
    return engine.startswith(("rss:", "direct_fetch:", "browser:"))


def _recommend_action(
    *,
    observations: int,
    candidates: int,
    results: int,
    raw_selected: int,
    observation_to_candidate_rate: float,
    reject_rate: float,
    result_rate: float,
    raw_selected_rate: float,
    dated_rate: float,
) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    next_steps: list[str] = []

    if observations and not candidates:
        reasons.append("parser produced observations but no admission candidates")
        next_steps.append("check parser-to-admission handoff before tuning source priority")
        return "investigate_parser", reasons, next_steps

    if results and dated_rate < LOW_DATED_RATE:
        reasons.append("result yield is usable but publication-date coverage is weak")
        next_steps.append("add detail-page date extraction, JSON-LD parsing, or sitemap date fallback")

    if (
        observations >= PROMOTE_MIN_OBSERVATIONS
        and results >= PROMOTE_MIN_RESULTS
        and result_rate >= PROMOTE_RESULT_RATE
        and raw_selected_rate >= PROMOTE_RAW_RATE
    ):
        reasons.append("source has enough observed items and survives into raw evidence")
        next_steps.append("consider higher fetch budget, pagination depth, or adjacent source discovery")
        return "promote", reasons, next_steps

    if candidates >= DEPRIORITIZE_MIN_CANDIDATES and reject_rate >= DEPRIORITIZE_REJECT_RATE and raw_selected == 0:
        reasons.append("source generates mostly rejected candidates with no raw evidence")
        next_steps.append("lower budget or tighten source-specific admission terms")
        return "deprioritize", reasons, next_steps

    if results >= PROMOTE_MIN_RESULTS and dated_rate < LOW_DATED_RATE:
        next_steps.append("keep current budget until dated coverage improves")
        return "improve_date_extraction", reasons, next_steps

    if observations and observation_to_candidate_rate < 0.5:
        reasons.append("many observations do not reach candidate audit")
        next_steps.append("inspect normalization and admission input construction")
        return "investigate_parser", reasons, next_steps

    if observations:
        reasons.append("source produced structured observations but needs more reviewed runs")
        next_steps.append("keep in review queue and compare against future health records")
        return "keep_review", reasons, next_steps

    reasons.append("no structured observations in this run")
    next_steps.append("leave unchanged until the source produces parser output")
    return "no_signal", reasons, next_steps


def _totals(sources: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "sources": len(sources),
        "observations": 0,
        "candidates": 0,
        "results": 0,
        "raw_selected": 0,
        "actions": defaultdict(int),
    }
    for source in sources:
        metrics = source["metrics"]
        totals["observations"] += metrics["observations"]
        totals["candidates"] += metrics["candidates"]
        totals["results"] += metrics["results"]
        totals["raw_selected"] += metrics["raw_selected"]
        totals["actions"][source["recommendation"]["action"]] += 1
    totals["actions"] = dict(sorted(totals["actions"].items()))
    return totals


def _rate(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator, 3)


def _action_rank(action: str) -> int:
    return {
        "promote": 0,
        "improve_date_extraction": 1,
        "investigate_parser": 2,
        "keep_review": 3,
        "deprioritize": 4,
        "no_signal": 5,
    }.get(action, 9)


def _read_json(path: str, *, default: Any) -> Any:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default
    return data if isinstance(data, type(default)) else default


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for manual source expansion analysis."""
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate watchlist source expansion signals.")
    parser.add_argument("run_data_dir", help="Run data directory containing watchlist sidecars and raw.json.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    args = parser.parse_args(argv)
    path = write_source_expansion_report(args.run_data_dir, args.output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
