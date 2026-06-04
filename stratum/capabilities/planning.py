"""Capability wrappers for planning and evaluation surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from stratum.evaluation import evaluate_cases, load_cases
from stratum.orchestrator import run_context
from stratum.orchestrator import signal_attach
from stratum.subsystems.event_thread import generate_watch_queries


def evaluate_reports(*, cases_path: str) -> dict[str, Any]:
    """Run deterministic report evaluation and return a structured summary."""
    summary = evaluate_cases(load_cases(cases_path))
    return summary.to_dict()


def watch_queries(
    *,
    threads: dict[str, Any],
    max_queries: int = 12,
    locales: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Generate next-run watch queries from thread state."""
    return generate_watch_queries(
        threads=threads,
        max_queries=max_queries,
        locales=locales,
    )


def attach_signal(
    *,
    domain: str,
    run_date: str,
    config_path: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Attach signal-awareness dry-run outputs to an existing daily run only."""
    config = _load_runtime_config(config_path)
    runtime_dirs = run_context.resolve_runtime_dirs(config, output_dir)
    paths = run_context.resolve_paths(domain, run_date, runtime_dirs.reports_dir, "daily")
    return signal_attach.run_attach(
        domain_id=domain,
        run_date=run_date,
        reports_dir=runtime_dirs.reports_dir,
        data_dir=paths["data_dir"],
    )


def _load_runtime_config(config_path: str | None) -> dict[str, Any]:
    path = Path(config_path or signal_attach.CONFIG_PATH)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}
