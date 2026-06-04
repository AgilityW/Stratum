"""Stable package surface for signal-awareness detection and preparation planning."""

from .anchors import normalize_anchor_registry, summarize_anchor_mentions
from .planning import build_activation_plan
from .runner import detect_signal_awareness, write_signal_awareness
from .topics import normalize_topic_rules

__all__ = [
    "build_activation_plan",
    "detect_signal_awareness",
    "normalize_anchor_registry",
    "normalize_topic_rules",
    "summarize_anchor_mentions",
    "write_signal_awareness",
]
