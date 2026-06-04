"""Stable package surface for reusable Stratum subsystems.

Subsystems package deterministic story/event/monitoring capabilities that can
be reused by the pipeline, DB-native synthesis, and future services without
forcing callers to reach into individual directories first.
"""

from . import event_thread, monitoring, signal_awareness, story_tracking

__all__ = [
    "event_thread",
    "monitoring",
    "signal_awareness",
    "story_tracking",
]
