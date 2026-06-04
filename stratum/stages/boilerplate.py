"""Shared boilerplate cleanup rules for stage evidence and artifacts.

These helpers define the domain-configurable `pipeline.boilerplate` contract
used by both Edit and Validate. Raw acquisition/search artifacts remain
unchanged; callers apply these rules only to stage-local evidence surfaces and
generated stage artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


GENERIC_CUT_MARKERS = (
    "#### \u63a8\u8350",
    "### \u63a8\u8350",
    "\u626b\u7801\u5173\u6ce8\u6211\u4eec",
    "Copyright©",
    "Copyright ©",
    "All rights reserved",
)

GENERIC_LINE_PATTERNS = (
    r"^#{2,6}\s*(\u63a8\u8350|\u63a8\u8350\u9605\u8bfb|\u76f8\u5173\u9605\u8bfb|\u76f8\u5173\u8d44\u8baf|\u76f8\u5173\u6587\u7ae0|\u5ef6\u4f38\u9605\u8bfb|\u6807\u7b7e:?|Tag[s]?:?)\s*$",
    r"^\u626b\u7801\u5173\u6ce8\u6211\u4eec\s*$",
    r"^.*(\u626b\u7801|\u4e8c\u7ef4\u7801).*(\u5173\u6ce8|\u8ba2\u9605).*$",
    r"^\u5ba2\u670d\u90ae\u7bb1[:\uff1a]?.*$",
    r"^.*(\bapp\b|\u624b\u673a\u7f51\u9875\u7248|\u5fae\u4fe1\u5c0f\u7a0b\u5e8f).*$",
    r"^.*ICP\u5907.*$",
    r"^.*\u516c\u7f51\u5b89\u5907.*$",
    r"^Copyright\s*©?.*$",
)


@dataclass(frozen=True)
class BoilerplateHit:
    rule_type: str
    pattern: str
    text: str
    source: str = ""


def source_domain(source: str | dict | None) -> str:
    if not source:
        return ""
    if isinstance(source, dict):
        raw = (
            source.get("source_domain")
            or source.get("source")
            or source.get("url")
            or ""
        )
    else:
        raw = str(source)
    raw = str(raw).strip().lower()
    if "://" in raw:
        raw = urlparse(raw).netloc.lower()
    raw = raw.split("/")[0]
    for prefix in ("www.", "m."):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    return raw


def _domain_matches(domain: str, patterns: list[str]) -> bool:
    if not domain:
        return False
    return any(domain == pattern or domain.endswith("." + pattern) for pattern in patterns)


def build_boilerplate_rules(config: dict | None = None) -> dict:
    """Merge framework-generic and domain/source-owned boilerplate rules."""
    config = config or {}
    rules = {
        "cut_markers": list(GENERIC_CUT_MARKERS),
        "line_patterns": list(GENERIC_LINE_PATTERNS),
        "source_rules": [],
    }
    rules["cut_markers"].extend(str(v) for v in config.get("cut_markers") or [])
    rules["line_patterns"].extend(str(v) for v in config.get("line_patterns") or [])
    for entry in config.get("source_rules") or []:
        if not isinstance(entry, dict):
            continue
        domains = [source_domain(domain) for domain in entry.get("domains") or []]
        rules["source_rules"].append({
            "domains": [domain for domain in domains if domain],
            "cut_markers": [str(v) for v in entry.get("cut_markers") or []],
            "line_patterns": [str(v) for v in entry.get("line_patterns") or []],
        })
    return rules


def _active_rule_sets(rules: dict | None, source: str | dict | None) -> tuple[list[str], list[str]]:
    rules = build_boilerplate_rules(rules)
    markers = list(rules.get("cut_markers") or [])
    patterns = list(rules.get("line_patterns") or [])
    domain = source_domain(source)
    for source_rule in rules.get("source_rules") or []:
        if _domain_matches(domain, source_rule.get("domains") or []):
            markers.extend(source_rule.get("cut_markers") or [])
            patterns.extend(source_rule.get("line_patterns") or [])
    return markers, patterns


def boilerplate_hits(text: str, source: str | dict | None = None, rules: dict | None = None) -> list[BoilerplateHit]:
    """Return rule hits without mutating text."""
    body = str(text or "")
    domain = source_domain(source)
    markers, patterns = _active_rule_sets(rules, source)
    hits: list[BoilerplateHit] = []
    for marker in markers:
        if marker and marker in body:
            hits.append(BoilerplateHit("cut_marker", marker, marker, domain))
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in patterns:
            if re.match(pattern, stripped, re.IGNORECASE):
                hits.append(BoilerplateHit("line_pattern", pattern, stripped, domain))
                break
    return hits


def clean_evidence_text(text: str, source: str | dict | None = None, rules: dict | None = None) -> str:
    """Remove source-site boilerplate before evidence reaches stage prompts."""
    cleaned = str(text or "")
    markers, patterns = _active_rule_sets(rules, source)
    cut_positions = [cleaned.find(marker) for marker in markers if marker and marker in cleaned]
    if cut_positions:
        cleaned = cleaned[:min(cut_positions)]
    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if any(re.match(pattern, stripped, re.IGNORECASE) for pattern in patterns):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def clean_article_evidence(article: dict, rules: dict | None = None) -> dict:
    """Return an article copy with text evidence cleaned, preserving raw inputs elsewhere."""
    cleaned = dict(article)
    for key in ("snippet", "extracted_summary"):
        if key in cleaned:
            cleaned[key] = clean_evidence_text(cleaned.get(key) or "", source=article, rules=rules)
    return cleaned


def artifact_boilerplate_violations(text: str, rules: dict | None = None) -> list[dict]:
    """Find boilerplate leaks in generated Markdown/JSON-like artifacts."""
    rules = build_boilerplate_rules(rules)
    artifact_rules = {
        "cut_markers": list(rules.get("cut_markers") or []),
        "line_patterns": list(rules.get("line_patterns") or []),
        "source_rules": [],
    }
    for source_rule in rules.get("source_rules") or []:
        artifact_rules["cut_markers"].extend(source_rule.get("cut_markers") or [])
        artifact_rules["line_patterns"].extend(source_rule.get("line_patterns") or [])
    return [
        {
            "rule_type": hit.rule_type,
            "pattern": hit.pattern,
            "text": hit.text[:160],
            "source": hit.source,
        }
        for hit in boilerplate_hits(text, rules=artifact_rules)
    ]


__all__ = [
    "BoilerplateHit",
    "artifact_boilerplate_violations",
    "boilerplate_hits",
    "build_boilerplate_rules",
    "clean_article_evidence",
    "clean_evidence_text",
    "source_domain",
]
