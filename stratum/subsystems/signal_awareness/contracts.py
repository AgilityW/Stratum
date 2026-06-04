"""File and payload contracts for the signal-awareness subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AwarenessFile:
    """Stable signal-awareness filename contract."""

    key: str
    filename: str
    file_format: str


SIGNAL_AWARENESS = AwarenessFile("signal_awareness", "signal_awareness.json", "json")
SIGNAL_ACTIVATION_PLAN = AwarenessFile("signal_activation_plan", "signal_plan.json", "json")

OUTPUT_FILES = (
    SIGNAL_AWARENESS,
    SIGNAL_ACTIVATION_PLAN,
)


def validate_output_payload(key: str, payload: Any) -> None:
    """Lightweight output guard for runner writes."""
    if not isinstance(payload, dict):
        raise TypeError(f"{key} must be an object payload")
