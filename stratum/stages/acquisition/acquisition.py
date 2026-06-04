#!/usr/bin/env python3
"""acquisition.py — broad discovery supplement for raw evidence acquisition.

Reads discovery provider settings from config.yaml and queries from either
SQLite or domains/{domain}/queries.yaml. Executes the shared
stratum.sourcing.discovery subsystem, then writes the broad discovery
supplement merged with any higher-priority watchlist raw results to raw.json
plus a sidecar stats file.

Usage:
    python3 acquisition.py --domain storage --date 2026-05-30 \
        --config config.yaml --queries domains/storage/queries.yaml \
        --output raw.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

import yaml

from stratum.contracts.pipeline_artifacts import DISCOVERY_CANDIDATES, DISCOVERY_OBSERVATIONS
from stratum.db.service import (
    load_active_search_queries_from_path,
    load_latest_search_engine_health_from_path,
)
from stratum.sourcing.discovery import (
    normalize_include_domains,
    SearchSupplementPolicy,
    split_queries_by_coverage,
)


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
    return load_active_search_queries_from_path(db_path)


def resolve_queries(
    domain: str,
    run_date: str,
    db_path: str | None,
    queries_path: str | None,
    workspace: str,
) -> tuple[list[dict], str]:
    """Choose the strongest available broad-discovery query source.

    SQLite is preferred when it has active daily queries because it can include
    story-tracking followups. A DB file alone is not enough: freshly created or
    unseeded databases would otherwise produce a zero-query acquisition run.
    In that case, fall back to the domain YAML baseline when available.
    """
    db_error = ""
    if db_path and os.path.exists(db_path):
        try:
            db_queries = load_queries_from_db(domain, db_path, workspace)
        except Exception as exc:
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


def load_existing_raw(path: str | None) -> list[dict]:
    """Load existing watchlist results used as higher-priority evidence."""
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("results", [])


def merge_raw_results(primary_results: list[dict], secondary_results: list[dict]) -> list[dict]:
    """Compatibility wrapper for higher-priority raw/discovery supplement merge."""
    return SearchSupplementPolicy(primary_results).merge_results(secondary_results)


def skipped_query_stats(skipped_queries: list[dict]) -> list[dict]:
    """Compatibility wrapper for skipped-query stats emitted by discovery policy."""
    return SearchSupplementPolicy().skipped_query_stats(skipped_queries)


def discovery_candidates_path(output_path: str) -> str:
    """Return the broad discovery candidate audit path beside raw.json."""
    return os.path.join(os.path.dirname(output_path), DISCOVERY_CANDIDATES.filename)


def discovery_observations_path(output_path: str) -> str:
    """Return the broad discovery observation path beside raw.json."""
    return os.path.join(os.path.dirname(output_path), DISCOVERY_OBSERVATIONS.filename)


def discovery_candidate_rows(result_set) -> list[dict]:
    """Build raw discovery candidate audit rows with curator selection state."""
    selected = {
        result.canonical_url or result.url
        for result in result_set.results
    }
    rows = []
    for result in result_set.raw_results:
        item = result.to_dict()
        canonical = item.get("canonical_url") or item.get("url", "")
        item["status"] = "selected" if canonical in selected else "rejected"
        item["selected"] = canonical in selected
        item["reason"] = "curated evidence pool" if item["selected"] else "curation pruned"
        rows.append(item)
    return rows


def write_jsonl(path: str, rows: list[dict]) -> None:
    """Write JSONL candidate audit records."""
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic broad discovery supplement via stratum.sourcing.discovery"
    )
    parser.add_argument("--domain", "-d", required=True, help="Domain ID, e.g. storage")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--start-date", help="Optional discovery window start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="Optional discovery window end date YYYY-MM-DD")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--workspace", help="Project workspace root; defaults to the config file directory")
    parser.add_argument("--queries", help="Path to queries.yaml; fallback when --db has no active queries")
    parser.add_argument("--db", help="Path to SQLite database; preferred when it has active queries")
    parser.add_argument("--output", "-o", required=True, help="Output raw.json path")
    parser.add_argument("--stats", help="Output stats.json path; default raw.stats.json")
    parser.add_argument("--existing-raw",
                        help="Higher-priority raw results from RSS/direct/browser to merge before discovery")
    parser.add_argument("--skip-covered-domain-queries", action="store_true",
                        help="Skip include_domains queries already covered by --existing-raw")
    args = parser.parse_args()

    workspace = os.path.abspath(args.workspace) if args.workspace else os.path.dirname(os.path.abspath(args.config))

    try:
        queries, query_source = resolve_queries(
            args.domain, args.date, args.db, args.queries, workspace
        )
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
    existing_raw = load_existing_raw(args.existing_raw)
    supplement_policy = SearchSupplementPolicy(existing_raw)
    queries, skipped_queries = supplement_policy.prepare_queries(
        queries,
        skip_covered_domain_queries=args.skip_covered_domain_queries,
    )
    if skipped_queries:
        print(
            f"📋 Skipped {len(skipped_queries)} covered domain-scoped queries",
            file=sys.stderr,
        )

    print(f"📋 Loaded {len(queries)} queries from {query_source}", file=sys.stderr)
    if not queries:
        if not existing_raw:
            print("❌ Acquisition loaded zero queries; seed DB or provide queries.yaml", file=sys.stderr)
            sys.exit(1)
        result_payload = supplement_policy.merge_results([])
        stats_payload = supplement_policy.zero_query_stats_payload(
            run_date=args.date,
            merged_results=result_payload,
            skipped_queries=skipped_queries,
        )
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result_payload, f, ensure_ascii=False, indent=2)
        stats_path = args.stats or args.output.replace(".json", ".stats.json")
        with open(stats_path, "w") as f:
            json.dump(stats_payload, f, ensure_ascii=False, indent=2)
        write_jsonl(discovery_observations_path(args.output), [])
        write_jsonl(discovery_candidates_path(args.output), [])
        print(f"✅ Acquisition: 0 discovery supplement; {len(result_payload)} total → {args.output}", file=sys.stderr)
        return

    from stratum.sourcing.discovery import load_api_keys, load_search_config, run_search

    config = load_search_config(args.domain, workspace, config_path=args.config)
    if args.db:
        engine_health = load_latest_search_engine_health_from_path(args.db)
        if engine_health:
            config["engine_health"] = engine_health
            print(
                f"📈 Loaded prior engine health for {len(engine_health)} search engines",
                file=sys.stderr,
            )
    api_keys = load_api_keys()
    result_set = run_search(
        queries,
        config,
        api_keys,
        args.date,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    search_raw = result_set.to_raw_json()
    merged_raw = supplement_policy.merge_results(search_raw)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(merged_raw, f, ensure_ascii=False, indent=2)

    stats_path = args.stats or args.output.replace(".json", ".stats.json")
    stats_payload = result_set.to_stats_json()
    stats_payload["total_raw"] = len(merged_raw)
    stats_payload.setdefault("diagnostics", {})["existing_raw"] = len(existing_raw)
    stats_payload.setdefault("diagnostics", {})["search_raw"] = len(search_raw)
    stats_payload.setdefault("diagnostics", {})["skipped_covered_queries"] = len(skipped_queries)
    stats_payload["queries"] = stats_payload.get("queries", []) + supplement_policy.skipped_query_stats(skipped_queries)
    with open(stats_path, "w") as f:
        json.dump(stats_payload, f, ensure_ascii=False, indent=2)
    write_jsonl(discovery_observations_path(args.output), getattr(result_set, "observations", []))
    write_jsonl(discovery_candidates_path(args.output), discovery_candidate_rows(result_set))

    print(
        f"✅ Acquisition: {len(search_raw)} discovery supplement, {result_set.total_curated} curated diagnostics "
        f"({len(merged_raw)} total raw) → {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
