"""Entity, term, and claim extraction algorithms for Normalize."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NumericClaim:
    """Typed numeric claim extracted from article text."""

    claim_type: str
    text: str
    value: float
    unit: str
    direction: str = "neutral"
    metric: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_type": self.claim_type,
            "text": self.text,
            "value": self.value,
            "unit": self.unit,
            "direction": self.direction,
            "metric": self.metric,
        }


class EntityResolver:
    """Resolve configured entity names from article text."""

    def __init__(self, flat_entities: list[str | dict]):
        self.entities = normalize_entity_records(flat_entities)

    def resolve(self, title: str, snippet: str) -> list[str]:
        return [match["label"] for match in self.resolve_matches(title, snippet)]

    def resolve_ids(self, title: str, snippet: str) -> list[str]:
        return [match["id"] for match in self.resolve_matches(title, snippet)]

    def resolve_matches(self, title: str, snippet: str) -> list[dict]:
        text = f"{title} {snippet}"
        found = []
        seen_ids = set()
        for entity in self.entities:
            if entity["id"] in seen_ids:
                continue
            if any(alias.lower() in text.lower() for alias in entity["aliases"]):
                found.append(entity)
                seen_ids.add(entity["id"])
        return found


class TermResolver:
    """Resolve configured, title-pattern, and thread-matched terms."""

    def __init__(self, flat_terms: list[str | dict]):
        self.terms = normalize_term_records(flat_terms)

    def resolve(self, title: str, snippet: str, thread_terms: list[str] | None = None) -> list[str]:
        base_terms = self.extract_static_terms(title, snippet)
        title_terms = self.extract_title_patterns(title)
        return list(dict.fromkeys(base_terms + title_terms + list(thread_terms or [])))

    def resolve_ids(self, title: str, snippet: str, thread_terms: list[str] | None = None) -> list[str]:
        ids = [match["id"] for match in self.resolve_matches(title, snippet)]
        ids.extend(slugify(term) for term in (thread_terms or []) if str(term).strip())
        return list(dict.fromkeys(ids))

    def resolve_matches(self, title: str, snippet: str) -> list[dict]:
        text = f"{title} {snippet}".lower()
        found = []
        seen_ids = set()
        for term in self.terms:
            if term["id"] in seen_ids:
                continue
            if any(alias.lower() in text for alias in term["aliases"]):
                found.append(term)
                seen_ids.add(term["id"])
        return found

    def extract_static_terms(self, title: str, snippet: str) -> list[str]:
        return [match["label"] for match in self.resolve_matches(title, snippet)]

    def extract_title_patterns(self, title: str) -> list[str]:
        if not title:
            return []

        patterns = [
            r"\b[A-Z]{2,}[-\s]?[A-Za-z]*[0-9]*[A-Za-z]*\b",
            r"\d+\s*(?:层|GB|TB|亿|万|％|%|nm|Mbps|Gbps)",
            r"[\u4e00-\u9fff]{2,}(?:存储|科技|电子|半导体|芯片|内存|闪存|海力士|美光|铠侠)",
        ]
        stopwords = {
            "半导体", "存储", "内存", "芯片", "NAND", "DRAM", "SSD", "HBM",
            "闪存", "涨价", "价格", "市场", "全球", "产业",
        }

        found = []
        stopword_keys = {stopword.lower() for stopword in stopwords}
        for pattern in patterns:
            for match in re.findall(pattern, title, re.IGNORECASE):
                value = match.strip()
                if value.lower() not in stopword_keys and value not in found:
                    found.append(value)
        return found


class ClaimExtractor:
    """Extract configured and typed numeric claim snippets."""

    def __init__(self, numeric_patterns: list[str]):
        self.numeric_patterns = numeric_patterns

    def extract_numeric_claims(self, snippet: str) -> list[str]:
        claims = [claim["text"] for claim in self.extract_typed_numeric_claims(snippet)]
        for pattern in self.numeric_patterns:
            matches = re.findall(pattern, snippet, re.IGNORECASE)
            claims.extend(matches)
        return list(dict.fromkeys(claims))

    def extract_typed_numeric_claims(self, text: str) -> list[dict]:
        """Extract typed numeric claims for downstream scoring and synthesis."""
        claims = []
        for pattern in TYPED_NUMERIC_PATTERNS:
            for match in re.finditer(pattern["regex"], text or "", re.IGNORECASE):
                raw_value = match.group(pattern.get("value_group", "value"))
                value = _to_float(raw_value)
                if value is None:
                    continue
                claim_text = match.group(0).strip()
                claims.append(NumericClaim(
                    claim_type=pattern["claim_type"],
                    text=claim_text,
                    value=value,
                    unit=pattern["unit"],
                    direction=_claim_direction(claim_text),
                    metric=pattern.get("metric", ""),
                ).to_dict())
        return _unique_claims(claims)


def extract_entities(title: str, snippet: str, flat_entities: list[str]) -> list[str]:
    """Compatibility wrapper for existing Normalize callers."""
    return EntityResolver(flat_entities).resolve(title, snippet)


def extract_terms(title: str, snippet: str, flat_terms: list[str]) -> list[str]:
    """Compatibility wrapper for existing Normalize callers."""
    return TermResolver(flat_terms).extract_static_terms(title, snippet)


def extract_title_patterns(title: str) -> list[str]:
    """Compatibility wrapper for existing Normalize callers."""
    return TermResolver([]).extract_title_patterns(title)


def extract_numeric_claims(snippet: str, numeric_patterns: list[str]) -> list[str]:
    """Compatibility wrapper for existing Normalize callers."""
    return ClaimExtractor(numeric_patterns).extract_numeric_claims(snippet)


def extract_typed_numeric_claims(snippet: str, numeric_patterns: list[str] | None = None) -> list[dict]:
    """Compatibility wrapper for typed numeric claim extraction."""
    return ClaimExtractor(numeric_patterns or []).extract_typed_numeric_claims(snippet)


def normalize_entity_records(values: list[str | dict]) -> list[dict]:
    """Normalize entity config strings or records into id/label/alias records."""
    return [_normalize_record(value) for value in values]


def normalize_term_records(values: list[str | dict]) -> list[dict]:
    """Normalize term config strings or records into id/label/alias records."""
    return [_normalize_record(value) for value in values]


def _normalize_record(value: str | dict) -> dict:
    if isinstance(value, dict):
        label = _record_label(value)
        aliases = _record_aliases(value, label)
        return {
            "id": str(value.get("id") or slugify(label)),
            "label": label,
            "aliases": aliases,
        }
    label = str(value).strip()
    return {"id": slugify(label), "label": label, "aliases": [label]}


def _record_label(value: dict) -> str:
    if value.get("label"):
        return str(value["label"]).strip()
    aliases = value.get("aliases")
    if isinstance(aliases, dict):
        for key in ("en", "zh-CN", "zh", "ja", "ko"):
            if aliases.get(key):
                return str(aliases[key]).strip()
        for alias in aliases.values():
            if alias:
                return str(alias).strip()
    if isinstance(aliases, list) and aliases:
        return str(aliases[0]).strip()
    return str(value.get("id") or "").strip()


def _record_aliases(value: dict, label: str) -> list[str]:
    aliases = [label, str(value.get("id") or "")]
    raw_aliases = value.get("aliases")
    if isinstance(raw_aliases, dict):
        aliases.extend(str(alias) for alias in raw_aliases.values() if alias)
    elif isinstance(raw_aliases, list):
        aliases.extend(str(alias) for alias in raw_aliases if alias)
    return list(dict.fromkeys(alias.strip() for alias in aliases if alias and alias.strip()))


def slugify(value: str) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


TYPED_NUMERIC_PATTERNS = [
    {
        "claim_type": "price_change",
        "metric": "price",
        "unit": "percent",
        "regex": r"(?:price|prices|pricing|contract price|spot price|合约价|现货价|价格)[^\n。.;]{0,40}?(?P<value>[+-]?\d+(?:\.\d+)?)\s*%",
    },
    {
        "claim_type": "asp_change",
        "metric": "asp",
        "unit": "percent",
        "regex": r"(?:ASP|average selling price|平均售价)[^\n。.;]{0,40}?(?P<value>[+-]?\d+(?:\.\d+)?)\s*%",
    },
    {
        "claim_type": "yield_rate",
        "metric": "yield",
        "unit": "percent",
        "regex": r"(?:yield|良率)[^\n。.;]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*%",
    },
    {
        "claim_type": "capacity",
        "metric": "capacity",
        "unit": "thousand_wpm",
        "regex": r"(?:capacity|wafer starts|WPM|月产能|产能)[^\n。.;]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*(?:k|K|thousand)\s*(?:wpm|wafers?|片/月)?",
    },
    {
        "claim_type": "capex",
        "metric": "capex",
        "unit": "usd_billion",
        "regex": r"(?:capex|capital expenditure|资本开支)[^\n。.;]{0,40}?\$?\s*(?P<value>\d+(?:\.\d+)?)\s*(?:billion|bn|十亿)",
    },
    {
        "claim_type": "shipment",
        "metric": "shipment",
        "unit": "million_units",
        "regex": r"(?:shipments?|出货|出货量)[^\n。.;]{0,40}?(?P<value>\d+(?:\.\d+)?)\s*(?:million|mn|百万)",
    },
    {
        "claim_type": "revenue",
        "metric": "revenue",
        "unit": "usd_billion",
        "regex": r"(?:revenue|sales|营收|销售额)[^\n。.;]{0,40}?\$?\s*(?P<value>\d+(?:\.\d+)?)\s*(?:billion|bn|十亿)",
    },
]


def _claim_direction(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["down", "decline", "fall", "drop", "cut", "decrease", "下降", "下滑", "减少", "削减"]):
        return "down"
    if any(token in lowered for token in ["up", "rise", "increase", "grow", "expand", "improve", "上升", "增长", "增加", "扩张", "改善"]):
        return "up"
    return "neutral"


def _to_float(value: str) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _unique_claims(claims: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for claim in claims:
        key = (claim["claim_type"], claim["text"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique
