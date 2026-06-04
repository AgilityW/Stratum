"""Stable package surface for temporal report contracts and execution."""

from .profiles import (
    DAILY_STAGE_ORDER,
    DB_NATIVE_STAGE_ORDER,
    HIGHER_TIMESCALES,
    TIMESCALES,
    TimescaleProfile,
    get_timescale_profile,
)

__all__ = [
    "DAILY_STAGE_ORDER",
    "DB_NATIVE_STAGE_ORDER",
    "Exploring",
    "ExploringDecision",
    "HIGHER_TIMESCALES",
    "Integration",
    "IntegrationDecision",
    "TIMESCALES",
    "TemporalServices",
    "TimescaleProfile",
    "get_timescale_profile",
    "run_exploring",
    "run_higher_scale_output",
]


def __getattr__(name: str):
    if name in ("Exploring", "ExploringDecision", "run_exploring"):
        from .exploring import Exploring, ExploringDecision, run_exploring
        return locals()[name]
    if name in ("Integration", "IntegrationDecision"):
        from .integration import Integration, IntegrationDecision
        return locals()[name]
    if name in ("TemporalServices", "run_higher_scale_output"):
        from .timescale import TemporalServices, run_higher_scale_output
        return locals()[name]
    raise AttributeError(f"module 'stratum.temporal' has no attribute '{name}'")
