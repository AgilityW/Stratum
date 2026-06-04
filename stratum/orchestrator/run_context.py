"""Shared CLI run context, path, stage, and manifest helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from stratum.contracts.pipeline_artifacts import DATA_DIR_ARTIFACTS, THREAD_KEYWORDS
from stratum.deployment import runtime_identity
from stratum.temporal import DAILY_STAGE_ORDER
from stratum.stages.render import artifact_basename


CST = timezone(timedelta(hours=8))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGES_DIR = os.path.join(PROJECT_ROOT, "stratum", "stages")
DOMAINS_DIR = os.path.join(PROJECT_ROOT, "domains")
PIPELINE_STAGE_ORDER = list(DAILY_STAGE_ORDER)
STAGE_ALIASES = {
    "search": "acquisition",
    "validate_recheck": "validate",
}


@dataclass(frozen=True)
class RuntimeDirs:
    """Resolved runtime roots for state, artifacts, and health outputs."""

    output_dir: str
    reports_dir: str
    db_dir: str
    health_data_dir: str


def _expand_runtime_path(value: str) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))


def resolve_runtime_dirs(config: dict, output_dir_override: str | None = None) -> RuntimeDirs:
    """Resolve runtime roots while keeping report artifacts and DB state separate."""
    output_dir = output_dir_override or config.get("output_dir", "")
    if not output_dir:
        raise ValueError("No output_dir set. Use --output-dir or configure config.yaml")
    output_dir = _expand_runtime_path(output_dir)

    reports_dir = config.get("reports_dir") or os.path.join(output_dir, "Reports")
    db_dir = config.get("db_dir") or os.path.join(output_dir, "DataBase")
    health_data_dir = config.get("health_data_dir") or os.path.join(output_dir, "health-data")

    reports_dir = _expand_runtime_path(reports_dir)
    db_dir = _expand_runtime_path(db_dir)
    health_data_dir = _expand_runtime_path(health_data_dir)

    if os.path.normcase(reports_dir) == os.path.normcase(db_dir):
        raise ValueError("reports_dir and db_dir must be separate directories")

    return RuntimeDirs(
        output_dir=output_dir,
        reports_dir=reports_dir,
        db_dir=db_dir,
        health_data_dir=health_data_dir,
    )


def resolve_paths(domain_id: str, run_date: str, output_dir: str, briefing_type: str = "daily") -> dict:
    """Resolve all file paths for a pipeline run."""
    domain_config = os.path.join(DOMAINS_DIR, domain_id, "domain.yaml")
    data_dir = (
        os.path.join(output_dir, domain_id, "data", run_date)
        if briefing_type == "daily"
        else os.path.join(output_dir, domain_id, "data", briefing_type, run_date)
    )
    artifact_base = artifact_basename(domain_id, briefing_type, run_date)
    paths = {
        "domain_config": domain_config,
        "data_dir": data_dir,
        "enriched": f"/tmp/strat_enriched_{domain_id}_{run_date}.json",
        "briefing_md": os.path.join(data_dir, f"{artifact_base}.md"),
        "briefing_html": os.path.join(data_dir, f"{artifact_base}.html"),
        "briefing_pdf": os.path.join(data_dir, f"{artifact_base}.pdf"),
        "story_tracking_dir": os.path.join(output_dir, domain_id, "data", "story-tracking"),
        "thread_keywords": os.path.join(
            output_dir,
            domain_id,
            "data",
            "story-tracking",
            THREAD_KEYWORDS.filename,
        ),
    }
    paths.update({spec.key: os.path.join(data_dir, spec.filename) for spec in DATA_DIR_ARTIFACTS})
    return paths


def run_stage(stage_name: str, stage_args: list[str], step_label: str, timeout: int = 120) -> bool:
    """Run a pipeline stage script, fail hard on error."""
    stage_name = STAGE_ALIASES.get(stage_name, stage_name)
    script = os.path.join(STAGES_DIR, stage_name, f"{stage_name}.py")
    cmd = [sys.executable, script] + stage_args
    env = os.environ.copy()
    env["PYTHONPATH"] = PROJECT_ROOT + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  STEP: {step_label}", file=sys.stderr)
    print(f"  CMD:  {' '.join(cmd)}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        _write_timeout_output(exc)
        print(f"\n❌ {step_label} TIMED OUT after {timeout}s", file=sys.stderr)
        return False

    sys.stderr.write(result.stderr)
    if result.stdout.strip():
        sys.stderr.write(result.stdout[:500])
    if result.returncode != 0:
        print(f"\n❌ {step_label} FAILED (exit {result.returncode})", file=sys.stderr)
        print(result.stderr[-500:], file=sys.stderr)
        return False
    print(f"✅ {step_label} complete", file=sys.stderr)
    return True


def should_run_stage(from_stage: str | None, stage_name: str) -> bool:
    """Return True if stage_name is at or after the requested resume point."""
    start = STAGE_ALIASES.get(from_stage or "acquisition", from_stage or "acquisition")
    stage_name = STAGE_ALIASES.get(stage_name, stage_name)
    try:
        start_idx = PIPELINE_STAGE_ORDER.index(start)
        stage_idx = PIPELINE_STAGE_ORDER.index(stage_name)
    except ValueError as exc:
        valid = ", ".join(PIPELINE_STAGE_ORDER)
        raise ValueError(
            f"Unknown pipeline stage in resume gate: from_stage={from_stage!r}, "
            f"stage_name={stage_name!r}. Valid stages: {valid}"
        ) from exc
    return stage_idx >= start_idx


def record_stage_status(
    pipeline_status: list[dict],
    stage: str,
    status: str,
    output: str | None = None,
    detail: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Append a structured stage status record for the run manifest."""
    record = {"stage": stage, "status": status, "timestamp": datetime.now(CST).isoformat()}
    if output:
        record["output"] = output
    if detail:
        record["detail"] = detail
    if metrics:
        record["metrics"] = metrics
    pipeline_status.append(record)


def write_run_manifest(
    manifest_path: str,
    domain: str,
    run_date: str,
    status: str,
    stages: list[dict],
    paths: dict,
    summary: dict | None = None,
    runtime: dict | None = None,
) -> dict:
    """Write the structured pipeline manifest and return its payload."""
    payload = {
        "status": status,
        "domain": domain,
        "date": run_date,
        "generated_at": datetime.now(CST).isoformat(),
        "runtime": runtime or runtime_identity(),
        "stages": stages,
        "summary": summary or {},
        "paths": {k: v for k, v in paths.items()},
    }
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def db_ingest_modes(from_stage: str | None, skip_agent: bool = False) -> dict[str, bool]:
    """Return which DB ingest surfaces may have fresh data in this run."""
    return {
        "events": should_run_stage(from_stage, "edit") and not skip_agent,
        "entities": should_run_stage(from_stage, "normalize"),
    }


def expanded_source_locales(config: dict) -> list[str]:
    """Expand configured source_languages into concrete locale tags."""
    source_languages = config.get("source_languages", []) or ["en"]
    locale_expansions = config.get("locales", {}) or {}
    locales = []
    for lang in source_languages:
        for locale in locale_expansions.get(lang) or [lang]:
            if locale not in locales:
                locales.append(locale)
    return locales or ["en"]


def should_export_thread_keywords_after_ingest(ingest_modes: dict, db_status: dict) -> bool:
    """Return True when SQLite has fresh event data for next-run keywords."""
    return bool(ingest_modes.get("events")) and db_status.get("status") == "success"


def _write_timeout_output(exc: subprocess.TimeoutExpired) -> None:
    stderr = exc.stderr or ""
    stdout = exc.stdout or ""
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    sys.stderr.write(stderr)
    if stdout.strip():
        sys.stderr.write(stdout[:500])
