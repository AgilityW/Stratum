"""Freshness and date-confidence policy for Verify."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


CST = timezone(timedelta(hours=8))

DATE_SOURCE_CONFIDENCE = {
    "search_api": "high",
    "web_extract": "high",
    "url_path": "high",
    "freshness_window": "medium",
    "snippet_regex": "low",
    "none": "none",
    "": "none",
}
CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class FreshnessDecision:
    """Date policy decision for an enriched article."""

    passed: bool
    status: str
    published_at: str | None
    date_source: str
    date_confidence: str
    quality_flags: list[str]


class FreshnessPolicy:
    """Own date validation, confidence, and background-evidence admission."""

    def __init__(self, date_window: dict | None = None):
        self.date_window = date_window or {}

    def evaluate(self, article: dict, run_date_str: str) -> FreshnessDecision:
        passed, status, parsed_date, date_source = self.validate_date(article, run_date_str)
        date_confidence = date_confidence_for_source(date_source)
        quality_flags: list[str] = []

        if not passed:
            admitted, background_date, background_source, flags = self.background_decision(
                article, status, parsed_date, run_date_str
            )
            if not admitted:
                return FreshnessDecision(
                    passed=False,
                    status=status,
                    published_at=parsed_date,
                    date_source=date_source,
                    date_confidence=date_confidence,
                    quality_flags=[],
                )
            parsed_date = background_date
            date_source = background_source or date_source
            date_confidence = date_confidence_for_source(date_source)
            quality_flags = flags

        if date_confidence == "low":
            quality_flags = list(dict.fromkeys(quality_flags + ["LOW_CONFIDENCE_DATE"]))

        min_date_confidence = self.date_window.get("min_date_confidence", "low")
        if not date_confidence_meets_minimum(date_confidence, min_date_confidence):
            return FreshnessDecision(
                passed=False,
                status="LOW_CONFIDENCE_DATE",
                published_at=parsed_date,
                date_source=date_source,
                date_confidence=date_confidence,
                quality_flags=quality_flags,
            )

        return FreshnessDecision(
            passed=True,
            status="verified",
            published_at=parsed_date,
            date_source=date_source,
            date_confidence=date_confidence,
            quality_flags=quality_flags,
        )

    def validate_date(self, article: dict, run_date_str: str) -> tuple[bool, str, str | None, str]:
        """Validate article date against the configured run-date window."""
        stale_days = stale_days_for_article(article, self.date_window)
        max_future_days = self.date_window.get("max_future_days", 1)

        date_str = extract_date_from_metadata(article)
        date_source = article.get("date_source", "")

        if not date_str:
            snippet = article.get("snippet", "") or article.get("description", "")
            title = article.get("title", "")
            text = f"{title} {snippet}"
            date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", text)
            if date_match:
                date_str = date_match.group(1)
                date_source = date_source or "snippet_regex"
            else:
                return False, "NO_DATE", None, date_source or "none"
        elif not date_source:
            date_source = "search_api"

        dt = parse_date(date_str)
        if dt is None:
            return False, "NO_DATE", None, date_source

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CST)

        run_date = datetime.fromisoformat(run_date_str).replace(tzinfo=CST)
        diff_days = (run_date - dt).days

        if diff_days < -max_future_days:
            return False, "FUTURE", dt.isoformat(), date_source
        if diff_days > stale_days:
            return False, "STALE", dt.isoformat(), date_source

        return True, "verified", dt.isoformat(), date_source

    def background_decision(
        self,
        article: dict,
        status: str,
        parsed_date: str | None,
        run_date: str,
    ) -> tuple[bool, str | None, str | None, list[str]]:
        """Admit selected stale/no-date records as background evidence only."""
        source_type = source_type_hint(article)
        engine = engine_name(article)

        if status == "STALE" and parsed_date:
            allowed_types = {
                str(item).lower()
                for item in self.date_window.get("background_source_types", [])
            }
            if source_type not in allowed_types:
                return False, None, None, []
            background_stale_days = int(self.date_window.get("background_stale_days", 0) or 0)
            if background_stale_days <= int(self.date_window.get("stale_days", 2)):
                return False, None, None, []
            parsed_dt = parse_date(parsed_date)
            if not parsed_dt:
                return False, None, None, []
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=CST)
            run_dt = datetime.fromisoformat(run_date).replace(tzinfo=CST)
            if (run_dt - parsed_dt).days <= background_stale_days:
                return True, parsed_dt.isoformat(), "search_api", ["BACKGROUND_STALE"]

        if status == "NO_DATE":
            allowed_types = {
                str(item).lower()
                for item in self.date_window.get("background_no_date_source_types", [])
            }
            allowed_engines = [
                str(item).lower()
                for item in self.date_window.get("background_no_date_engines", [])
            ]
            if source_type in allowed_types and engine_allowed(engine, allowed_engines):
                run_dt = datetime.fromisoformat(run_date).replace(tzinfo=CST)
                return True, run_dt.isoformat(), "freshness_window", ["BACKGROUND_NO_DATE"]

        return False, None, None, []


def extract_date_from_metadata(article: dict) -> str | None:
    """Extract publication date from search API metadata."""
    if "datePublished" in article:
        return article["datePublished"]
    if "date_published" in article:
        return article["date_published"]
    if "published_date" in article:
        return article["published_date"]
    for key in ["publishedAt", "pubDate", "date", "timestamp"]:
        if key in article:
            return article[key]
    return None


def parse_date(date_str: str) -> datetime | None:
    """Parse various date formats to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    for fmt in [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %B %Y",
        "%B %d, %Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    return None


def date_confidence_for_source(date_source: str) -> str:
    """Map date lineage to a deterministic confidence bucket."""
    return DATE_SOURCE_CONFIDENCE.get(date_source or "", "low")


def date_confidence_meets_minimum(confidence: str, minimum: str) -> bool:
    """Return whether a confidence bucket satisfies a configured minimum."""
    return CONFIDENCE_RANK.get(confidence, 0) >= CONFIDENCE_RANK.get(minimum, 0)


def validate_date(article: dict, run_date_str: str, date_window: dict) -> tuple[bool, str, str | None, str]:
    """Compatibility wrapper for existing Verify callers."""
    return FreshnessPolicy(date_window).validate_date(article, run_date_str)


def background_flags_for_date_failure(
    article: dict,
    status: str,
    parsed_date: str | None,
    run_date: str,
    date_window: dict,
) -> tuple[bool, str | None, str | None, list[str]]:
    """Compatibility wrapper for existing Verify callers."""
    return FreshnessPolicy(date_window).background_decision(article, status, parsed_date, run_date)


def source_type_hint(article: dict) -> str:
    raw = article.get("raw_metadata", {}) if isinstance(article.get("raw_metadata"), dict) else {}
    return str(
        article.get("source_type")
        or article.get("source_type_hint")
        or raw.get("source_type")
        or raw.get("source_type_hint")
        or ""
    ).strip().lower()


def stale_days_for_article(article: dict, date_window: dict) -> int:
    """Return the source-type-specific stale window for an article."""
    default_stale_days = int(date_window.get("stale_days", 2))
    source_type_windows = date_window.get("source_type_stale_days", {}) or {}
    source_type = source_type_hint(article)
    if source_type in source_type_windows:
        return int(source_type_windows[source_type])
    return default_stale_days


def engine_name(article: dict) -> str:
    raw = article.get("raw_metadata", {}) if isinstance(article.get("raw_metadata"), dict) else {}
    return str(article.get("engine") or raw.get("engine") or "").strip().lower()


def engine_allowed(engine: str, prefixes: list[str]) -> bool:
    return any(engine == prefix or engine.startswith(f"{prefix}:") for prefix in prefixes)
