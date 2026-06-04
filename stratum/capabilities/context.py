"""Capability wrappers for semantic read surfaces and domain-owned config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from stratum.db import service


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def report_context(
    *,
    domain: str,
    scale: str,
    period: str,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    """Return report-semantic context through a stable capability wrapper."""
    return service.get_report_context(
        domain,
        scale,
        period,
        window_start=window_start,
        window_end=window_end,
    )


def story_context(*, domain: str) -> dict[str, list[dict[str, Any]]]:
    """Return daily story-context records through a stable capability wrapper."""
    return service.get_story_context_records(domain)


def awareness_config(domain: str) -> dict[str, Any]:
    """Load the optional domain-owned signal-awareness config."""
    path = PROJECT_ROOT / "domains" / domain / "signal_awareness.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}
