"""Term normalization for Signal Bursts."""

from __future__ import annotations

from typing import Any


def normalize_terms(terms: list[Any]) -> list[dict[str, Any]]:
    """Normalize caller-provided terms and aliases.

    Supported inputs:
    - "hbm4"
    - {"id": "hbm4", "aliases": ["HBM4", "high bandwidth memory 4"]}
    - {"term": "hbm4", "aliases": {"en": "HBM4", "zh": "高带宽内存"}}
    """
    normalized = []
    seen = set()
    for item in terms:
        if isinstance(item, str):
            term_id = _slug(item)
            aliases = [item]
        elif isinstance(item, dict):
            label = str(item.get("id") or item.get("term") or item.get("label") or "")
            term_id = _slug(label)
            aliases = _aliases(item.get("aliases")) or [label]
        else:
            continue
        if not term_id or term_id in seen:
            continue
        seen.add(term_id)
        alias_values = sorted({_clean(alias) for alias in aliases if _clean(alias)}, key=len, reverse=True)
        normalized.append({
            "id": term_id,
            "label": aliases[0] if aliases else term_id,
            "aliases": alias_values,
        })
    return normalized


def match_terms(text: str, terms: list[dict[str, Any]]) -> list[str]:
    """Return term ids whose aliases appear in text."""
    haystack = _clean(text)
    if not haystack:
        return []
    hits = []
    for term in terms:
        for alias in term.get("aliases", []):
            if alias and alias in haystack:
                hits.append(term["id"])
                break
    return hits


def _aliases(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(item) for item in value.values() if item]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value]
    return []


def _slug(value: str) -> str:
    return _clean(value).replace(" ", "_")


def _clean(value: str) -> str:
    return " ".join(str(value or "").lower().split())
