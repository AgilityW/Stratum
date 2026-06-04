"""Load SourceTrace inputs from a run artifact directory."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .contracts import INPUT_FILES
from .db_context import normalize_db_context


def load_inputs(input_dir: str, *, db_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load all known SourceTrace input files from a directory."""
    payload: dict[str, Any] = {}
    for spec in INPUT_FILES:
        path = os.path.join(input_dir, spec.filename)
        if spec.file_format == "jsonl":
            rows, errors = load_jsonl(path)
            payload[spec.key] = [_normalize_record(row) for row in rows]
            payload[f"{spec.key}_errors"] = errors
        else:
            data = load_json(path)
            rows = data if isinstance(data, list) else data.get("results", []) if isinstance(data, dict) else []
            payload[spec.key] = [_normalize_record(row) for row in rows if isinstance(row, dict)]
    payload["db_context"] = normalize_db_context(db_context)
    payload["input_dir"] = input_dir
    return payload


def load_json(path: str) -> Any:
    """Load JSON, returning an empty list for missing or malformed files."""
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def load_jsonl(path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load JSONL with malformed rows isolated into an error list."""
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not os.path.exists(path):
        return rows, errors
    with open(path) as f:
        for lineno, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append({"line": lineno, "error": str(exc), "raw": text[:500]})
                continue
            if isinstance(item, dict):
                rows.append(item)
            else:
                errors.append({"line": lineno, "error": "row is not an object", "raw": text[:500]})
    return rows, errors


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    item = dict(record)
    item.setdefault("canonical_url", _canonical_url(item.get("canonical_url") or item.get("url") or ""))
    if not item.get("source"):
        item["source"] = _source(item)
    return item


def _source(item: dict[str, Any]) -> str:
    engine = str(item.get("engine") or "")
    if ":" in engine:
        return engine.split(":", 1)[1]
    return str(item.get("source_domain") or item.get("domain") or "unknown")


def _canonical_url(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    query = urlencode([
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ])
    return urlunparse((parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/", "", query, ""))
