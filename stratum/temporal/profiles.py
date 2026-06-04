"""Report timescale profiles.

Profiles describe which stages are shared and where each report timescale has
its own contract. They are intentionally small data objects so daily, weekly,
monthly, quarterly, and yearly runners can use the same temporal vocabulary
without sharing one oversized implementation.
"""

from __future__ import annotations

from dataclasses import dataclass


TIMESCALES = ("daily", "weekly", "monthly", "quarterly", "yearly")
HIGHER_TIMESCALES = ("weekly", "monthly", "quarterly", "yearly")

DAILY_STAGE_ORDER = (
    "acquisition",
    "enrich",
    "verify",
    "normalize",
    "cluster",
    "edit",
    "validate",
    "repair",
    "validate_recheck",
    "render",
)

DB_NATIVE_STAGE_ORDER = (
    "exploring",
    "db_synthesis",
    "markdown",
    "render",
)


@dataclass(frozen=True)
class TimescaleProfile:
    """Temporal contract for one report timescale."""

    scale: str
    label_zh: str
    cadence_zh: str
    template_name: str
    stage_order: tuple[str, ...]
    uses_daily_pipeline: bool
    consumes_lower_scales: bool
    consumes_same_scale_fresh_evidence: bool
    synthesis_policy_profile: str | None = None


_PROFILES = {
    "daily": TimescaleProfile(
        scale="daily",
        label_zh="日报",
        cadence_zh="每日 7:30 CST",
        template_name="daily.html",
        stage_order=DAILY_STAGE_ORDER,
        uses_daily_pipeline=True,
        consumes_lower_scales=False,
        consumes_same_scale_fresh_evidence=False,
        synthesis_policy_profile=None,
    ),
    "weekly": TimescaleProfile(
        scale="weekly",
        label_zh="周报",
        cadence_zh="每周",
        template_name="weekly.html",
        stage_order=DB_NATIVE_STAGE_ORDER,
        uses_daily_pipeline=False,
        consumes_lower_scales=True,
        consumes_same_scale_fresh_evidence=True,
        synthesis_policy_profile="weekly",
    ),
    "monthly": TimescaleProfile(
        scale="monthly",
        label_zh="月报",
        cadence_zh="每月",
        template_name="monthly.html",
        stage_order=DB_NATIVE_STAGE_ORDER,
        uses_daily_pipeline=False,
        consumes_lower_scales=True,
        consumes_same_scale_fresh_evidence=True,
        synthesis_policy_profile="monthly",
    ),
    "quarterly": TimescaleProfile(
        scale="quarterly",
        label_zh="季报",
        cadence_zh="每季",
        template_name="quarterly.html",
        stage_order=DB_NATIVE_STAGE_ORDER,
        uses_daily_pipeline=False,
        consumes_lower_scales=True,
        consumes_same_scale_fresh_evidence=True,
        synthesis_policy_profile="quarterly",
    ),
    "yearly": TimescaleProfile(
        scale="yearly",
        label_zh="年报",
        cadence_zh="每年",
        template_name="yearly.html",
        stage_order=DB_NATIVE_STAGE_ORDER,
        uses_daily_pipeline=False,
        consumes_lower_scales=True,
        consumes_same_scale_fresh_evidence=True,
        synthesis_policy_profile="yearly",
    ),
}


def get_timescale_profile(scale: str) -> TimescaleProfile:
    """Return the configured profile for one timescale."""
    try:
        return _PROFILES[scale]
    except KeyError as exc:
        valid = ", ".join(TIMESCALES)
        raise ValueError(f"unsupported timescale: {scale}. Valid timescales: {valid}") from exc
