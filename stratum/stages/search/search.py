#!/usr/bin/env python3
"""search.py — deterministic search stage via stratum.subsystems.search.

Reads engine settings from config.yaml and queries from either SQLite or
domains/{domain}/queries.yaml. Executes the shared search subsystem, then writes
curated results to raw.json plus a sidecar stats file.

Usage:
    python3 search.py --domain storage --date 2026-05-30 \
        --config config.yaml --queries domains/storage/queries.yaml \
        --output raw.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

import yaml

from stratum.subsystems.search.models import normalize_include_domains


LOCALE_KEY_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def _substitute_query_text(text: str, substitutions: dict[str, str]) -> str:
    for key, value in substitutions.items():
        text = text.replace(key, value)
    return text


def _query_text(item) -> str:
    if isinstance(item, dict):
        return str(item.get("text", item.get("query", "")))
    return str(item)


def _query_id(item, fallback: str) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or fallback)
    return fallback


def _is_locale_key(value: str) -> bool:
    return bool(LOCALE_KEY_RE.match(str(value)))


def _query_dimension(item, fallback: str) -> str:
    if isinstance(item, dict):
        return str(item.get("dimension") or fallback)
    return fallback


def _query_include_domains(item) -> list[str]:
    if not isinstance(item, dict):
        return []
    domains = item.get("include_domains") or item.get("domains") or []
    return _normalize_include_domains(domains)


def _normalize_include_domains(domains) -> list[str]:
    return normalize_include_domains(domains)


def _parse_include_domains(value) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        parsed = value
    return _normalize_include_domains(parsed)


def _flatten_intent_queries(data: dict, substitutions: dict[str, str]) -> list[dict]:
    """Flatten structured queries into subsystem query dicts.

    Supports both:
      - queries: intent -> locale -> list
      - queries: intent -> dimension -> locale -> list
    """
    queries: list[dict] = []
    count = 0
    for intent, intent_map in data.get("queries", {}).items():
        if not isinstance(intent_map, dict):
            continue
        for key, value in intent_map.items():
            if _is_locale_key(key):
                count = _append_query_items(
                    queries, value, substitutions, intent, "general", key, count
                )
                continue
            if not isinstance(value, dict):
                continue
            dimension = str(key)
            for locale, qlist in value.items():
                count = _append_query_items(
                    queries, qlist, substitutions, intent, dimension, locale, count
                )
    return queries


def _append_query_items(
    queries: list[dict],
    items,
    substitutions: dict[str, str],
    intent: str,
    dimension: str,
    locale: str,
    count: int,
) -> int:
    for item in items or []:
        item_dimension = _query_dimension(item, dimension)
        text = _substitute_query_text(_query_text(item), substitutions)
        query = {
            "id": _query_id(item, f"q-{intent}-{item_dimension}-{count:03d}"),
            "text": text,
            "locale": locale,
            "intent": intent,
            "dimension": item_dimension,
        }
        include_domains = _query_include_domains(item)
        if include_domains:
            query["include_domains"] = include_domains
        queries.append(query)
        count += 1
    return count


def load_queries_flat(queries_path: str, run_date: str) -> list[dict]:
    """Load queries.yaml and flatten supported query structures."""
    with open(queries_path) as f:
        data = yaml.safe_load(f) or {}

    if "queries" not in data:
        raise ValueError(
            f"{queries_path} must define structured queries: "
            "intent -> dimension -> locale -> list"
        )

    dt = datetime.fromisoformat(run_date)
    substitutions = {
        "${CURRENT_YEAR}": str(dt.year),
        "${CURRENT_MONTH_EN}": dt.strftime("%B"),
        "${CURRENT_MONTH_ZH}": f"{dt.month}月",
    }

    return _flatten_intent_queries(data, substitutions)


def load_queries_from_db(domain: str, db_path: str, workspace: str) -> list[dict]:
    """Load active daily queries from the explicit SQLite path passed by CLI."""
    del domain, workspace
    if not os.path.exists(db_path):
        return []

    intents = ["detection", "verification"]
    thread_statuses = ["emerging", "active", "cooling"]
    intent_placeholders = ",".join(["?"] * len(intents))
    status_placeholders = ",".join(["?"] * len(thread_statuses))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        query_columns = {row["name"] for row in conn.execute("PRAGMA table_info(queries)").fetchall()}
        dimension_expr = "q.dimension" if "dimension" in query_columns else "'db'"
        include_domains_expr = "q.include_domains" if "include_domains" in query_columns else "NULL"
        db_queries = conn.execute(f"""
            SELECT q.id, q.text, q.locale, q.intent,
                   {dimension_expr} AS dimension,
                   {include_domains_expr} AS include_domains
            FROM queries q
            LEFT JOIN threads t ON q.thread_id = t.id
            WHERE q.status = 'active'
              AND (q.thread_id IS NULL OR t.status IN ({status_placeholders}))
              AND q.intent IN ({intent_placeholders})
            ORDER BY q.intent, q.locale
        """, thread_statuses + intents).fetchall()
    finally:
        conn.close()

    queries = []
    for q in db_queries:
        item = {
            "id": q["id"],
            "text": q["text"],
            "locale": q["locale"] or "en",
            "intent": q["intent"] or "detection",
            "dimension": q["dimension"] or "general",
        }
        include_domains = _parse_include_domains(q["include_domains"])
        if include_domains:
            item["include_domains"] = include_domains
        queries.append(item)
    return queries


def resolve_queries(
    domain: str,
    run_date: str,
    db_path: str | None,
    queries_path: str | None,
    workspace: str,
) -> tuple[list[dict], str]:
    """Choose the strongest available query source.

    SQLite is preferred when it has active daily queries because it can include
    story-tracking followups. A DB file alone is not enough: freshly created or
    unseeded databases would otherwise produce a zero-query search run. In that
    case, fall back to the domain YAML baseline when available.
    """
    db_error = ""
    if db_path and os.path.exists(db_path):
        try:
            db_queries = load_queries_from_db(domain, db_path, workspace)
        except sqlite3.Error as exc:
            db_queries = []
            db_error = f" ({type(exc).__name__}: {exc})"
        if db_queries:
            return db_queries, "DB"
        if queries_path:
            print(
                f"⚠️  DB produced no active daily queries{db_error}; falling back to YAML",
                file=sys.stderr,
            )

    if queries_path:
        return load_queries_flat(queries_path, run_date), "YAML"

    if db_path and os.path.exists(db_path):
        return [], "DB"

    raise FileNotFoundError("Either --queries or an existing --db is required")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic search via stratum.subsystems.search"
    )
    parser.add_argument("--domain", "-d", required=True, help="Domain ID, e.g. storage")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--queries", help="Path to queries.yaml; fallback when --db has no active queries")
    parser.add_argument("--db", help="Path to SQLite database; preferred when it has active queries")
    parser.add_argument("--output", "-o", required=True, help="Output raw.json path")
    parser.add_argument("--stats", help="Output stats.json path; default raw.stats.json")
    args = parser.parse_args()

    workspace = os.path.dirname(os.path.abspath(args.config))

    try:
        queries, query_source = resolve_queries(
            args.domain, args.date, args.db, args.queries, workspace
        )
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"📋 Loaded {len(queries)} queries from {query_source}", file=sys.stderr)
    if not queries:
        print("❌ Search loaded zero queries; seed DB or provide queries.yaml", file=sys.stderr)
        sys.exit(1)

    from stratum.subsystems.search import load_api_keys, load_search_config, run_search

    config = load_search_config(args.domain, workspace, config_path=args.config)
    api_keys = load_api_keys()
    result_set = run_search(queries, config, api_keys, args.date)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result_set.to_raw_json(), f, ensure_ascii=False, indent=2)

    stats_path = args.stats or args.output.replace(".json", ".stats.json")
    with open(stats_path, "w") as f:
        json.dump(result_set.to_stats_json(), f, ensure_ascii=False, indent=2)

    print(
        f"✅ Search: {result_set.total_curated} curated "
        f"(from {result_set.total_raw} raw) → {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
