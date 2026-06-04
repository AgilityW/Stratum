"""Signal Bursts input and output contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BurstOutput:
    """Stable Signal Bursts output file."""

    key: str
    filename: str


SIGNAL_BURSTS = BurstOutput("signal_bursts", "signal_bursts.json")

SOURCE_TRACE_LAYERS = (
    "watchlist_observations",
    "discovery_observations",
    "watchlist_candidates",
    "discovery_candidates",
    "watchlist_results",
    "raw",
)

DB_CONTEXT_KEYS = (
    "articles",
    "events",
    "threads",
    "judgments",
    "report_items",
    "evidence_links",
)


def empty_records_by_layer() -> dict[str, list[dict[str, Any]]]:
    """Return empty SourceTrace record layers."""
    return {key: [] for key in SOURCE_TRACE_LAYERS}


def empty_db_context() -> dict[str, list[dict[str, Any]]]:
    """Return empty DB context shape."""
    return {key: [] for key in DB_CONTEXT_KEYS}


def normalize_records_by_layer(records_by_layer: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Normalize SourceTrace raw layers for burst detection."""
    normalized = empty_records_by_layer()
    if not records_by_layer:
        return normalized
    for key in SOURCE_TRACE_LAYERS:
        value = records_by_layer.get(key, [])
        normalized[key] = value if isinstance(value, list) else []
    return normalized


def normalize_db_context(db_context: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Normalize DB read-model records."""
    normalized = empty_db_context()
    if not db_context:
        return normalized
    for key in DB_CONTEXT_KEYS:
        value = db_context.get(key, [])
        normalized[key] = value if isinstance(value, list) else []
    return normalized


def validate_payload(payload: dict[str, Any]) -> None:
    """Lightweight payload guard for Signal Bursts outputs."""
    if not isinstance(payload, dict):
        raise TypeError("signal_bursts payload must be an object")
    required_list_fields = (
        "terms",
        "burst_candidates",
        "bursts",
        "report_handoff",
        "recommendations",
    )
    required_dict_fields = (
        "co_occurrence",
        "diagnostics",
    )
    for key in required_list_fields:
        if not isinstance(payload.get(key), list):
            raise TypeError(f"signal_bursts.{key} must be a list")
    for key in required_dict_fields:
        if not isinstance(payload.get(key), dict):
            raise TypeError(f"signal_bursts.{key} must be an object")
    if not isinstance(payload.get("version"), str):
        raise TypeError("signal_bursts.version must be a string")
