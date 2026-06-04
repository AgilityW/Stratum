"""Report window contract shared by DB, runtime, and orchestration."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta


VALID_PERIOD_KINDS = ("standard", "custom_range")


@dataclass(frozen=True)
class ReportWindow:
    """A report profile plus the concrete inclusive date window it covers."""

    scale: str
    period: str
    start_date: str
    end_date: str
    period_kind: str = "standard"

    @property
    def label(self) -> str:
        if self.period_kind == "custom_range":
            return f"{self.start_date} to {self.end_date}"
        return self.period

    def to_dict(self) -> dict[str, str]:
        return {
            "scale": self.scale,
            "period": self.period,
            "start": self.start_date,
            "end": self.end_date,
            "period_kind": self.period_kind,
            "label": self.label,
        }


def resolve_report_window(
    scale: str,
    period: str | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ReportWindow:
    """Resolve a standard period or explicit date range into a ReportWindow."""
    if start_date or end_date:
        if not start_date or not end_date:
            raise ValueError("custom report windows require both start_date and end_date")
        _validate_iso_date(start_date)
        _validate_iso_date(end_date)
        if start_date > end_date:
            raise ValueError(f"start_date must be <= end_date: {start_date} > {end_date}")
        custom_period = period or custom_period_id(start_date, end_date)
        return ReportWindow(scale, custom_period, start_date, end_date, "custom_range")

    if period and period.startswith("custom-"):
        start, end = parse_custom_period(period)
        return ReportWindow(scale, period, start, end, "custom_range")

    if not period:
        raise ValueError("standard report windows require period")
    start, end = period_window(scale, period)
    return ReportWindow(scale, period, start, end, "standard")


def custom_period_id(start_date: str, end_date: str) -> str:
    """Return a stable period id for custom date ranges."""
    return f"custom-{start_date}_to_{end_date}"


def parse_custom_period(period: str) -> tuple[str, str]:
    match = re.fullmatch(r"custom-(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})", period)
    if not match:
        raise ValueError(f"invalid custom period id: {period}")
    return match.group(1), match.group(2)


def period_window(scale: str, period: str) -> tuple[str, str]:
    """Return inclusive daily date bounds for a scale/period."""
    if period.startswith("custom-"):
        return parse_custom_period(period)
    if scale == "daily":
        _validate_iso_date(period)
        return period, period
    if scale == "weekly":
        return _weekly_window(period)
    if scale == "monthly":
        return _monthly_window(period)
    if scale == "quarterly":
        return _quarterly_window(period)
    if scale == "yearly":
        start = date(int(period), 1, 1)
        end = date(int(period), 12, 31)
        return start.isoformat(), end.isoformat()
    _validate_iso_date(period)
    return period, period


def _weekly_window(period: str) -> tuple[str, str]:
    match = re.fullmatch(r"(\d{4})-W(\d{1,2})", period)
    if not match:
        raise ValueError(f"invalid weekly period: {period}")
    year = int(match.group(1))
    week = int(match.group(2))
    start = date.fromisocalendar(year, week, 1)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _monthly_window(period: str) -> tuple[str, str]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if not match:
        raise ValueError(f"invalid monthly period: {period}")
    year = int(match.group(1))
    month = int(match.group(2))
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return start.isoformat(), end.isoformat()


def _quarterly_window(period: str) -> tuple[str, str]:
    match = re.fullmatch(r"(\d{4})-Q([1-4])", period)
    if not match:
        raise ValueError(f"invalid quarterly period: {period}")
    year = int(match.group(1))
    quarter = int(match.group(2))
    start_month = 1 + (quarter - 1) * 3
    end_month = start_month + 2
    start = date(year, start_month, 1)
    end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    return start.isoformat(), end.isoformat()


def _validate_iso_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc

