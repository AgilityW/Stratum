#!/usr/bin/env python3
"""validate.py — Content gate: verify briefing .md claims trace back to verified articles.

Domain-agnostic. Source aliases loaded from domain.yaml.

Input:  briefing.md (LLM-written markdown) + articles.jsonl (verified/normalized articles)
Output: JSON to stdout — {status: "ok"|"violations", items, violations, details}
Side effects: None. Reads files, writes nothing except stderr logs.
Invariants:  Every cited source in .md must match a domain in articles.jsonl.
             Every cited date must be inside the domain date_window policy.
Error behavior: Source mismatch → SOURCE violation. Stale date → DATE violation.
                Missing source/date → flagged. Exit code 0 if clean, 1 if violations.

Usage:
    python3 validate.py --md briefing.md --articles articles.jsonl \
        --date 2026-05-28 --domain domains/storage/domain.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import yaml
from datetime import datetime, timezone, timedelta
from jsonschema import validate as json_validate, ValidationError

from stratum.stages.boilerplate import artifact_boilerplate_violations, build_boilerplate_rules
try:
    from .claim_validator import validate_overclaims
    from .source_support import SourceDatePolicy, SourceSupportMatcher
except ImportError:  # pragma: no cover - direct script/test fallback
    from stratum.stages.validate.claim_validator import validate_overclaims
    from stratum.stages.validate.source_support import SourceDatePolicy, SourceSupportMatcher

CST = timezone(timedelta(hours=8))
_SOURCE_SUPPORT = SourceSupportMatcher()
_SOURCE_DATES = SourceDatePolicy()


def load_domain_config(domain_path: str) -> dict:
    """Load pipeline section from domain.yaml."""
    with open(domain_path) as f:
        config = yaml.safe_load(f)
    return config.get("pipeline", {})


def load_articles(path):
    articles = []
    with open(path) as f:
        for line in f:
            if line.strip():
                articles.append(json.loads(line))
    return articles


def validate_boilerplate(markdown_text: str, pipeline_config: dict) -> list[str]:
    boilerplate_rules = build_boilerplate_rules(pipeline_config.get("boilerplate", {}))
    return [
        f"BOILERPLATE: {violation['text']} ({violation['rule_type']}: {violation['pattern']})"
        for violation in artifact_boilerplate_violations(markdown_text, boilerplate_rules)
    ]


def resolve_date_window(pipeline_config: dict, stale_days_override: int | None = None) -> tuple[int, int]:
    """Resolve future and stale date windows for briefing validation."""
    date_window = pipeline_config.get("date_window", {}) if isinstance(pipeline_config, dict) else {}
    max_future_days = int(date_window.get("max_future_days", 1))
    stale_days = (
        int(stale_days_override)
        if stale_days_override is not None
        else int(date_window.get("stale_days", 2))
    )
    return max_future_days, stale_days


def _parse_source_line(line: str) -> tuple[list[str], str | None] | None:
    """Parse an italic source line, ignoring generated footer lines."""
    source_line = line.strip('* ').strip()
    if any(x in source_line.lower() for x in ["ai agent", "本简报", "自动生成"]):
        return None

    parts = [p.strip() for p in source_line.split('·')]
    if len(parts) < 2:
        return None

    sources_part = parts[0]
    date_part = " · ".join(parts[1:]).strip()
    sources = [
        re.sub(r"\s*\[(?:[A-Za-z]{2,3}(?:-[A-Za-z]{2,8}){0,2})\]", "", s).strip()
        for s in sources_part.split(',')
        if s.strip()
    ]
    return sources, date_part


NON_NEWS_SECTION_TITLES = {"今日要点", "行业要点", "产业信号", "特别关注", "反向信号"}


def parse_markdown(path):
    """Parse briefing .md into structured sections."""
    with open(path) as f:
        content = f.read()

    items = []
    current_item = None

    for line in content.split('\n'):
        line = line.strip()

        if line.startswith('### '):
            title = line.replace('### ', '').strip()
            if title in NON_NEWS_SECTION_TITLES:
                continue
            if current_item:
                items.append(current_item)
            current_item = {
                'title': title,
                'body': [],
                'sources': [],
                'date': None,
            }
        elif line.startswith('## '):
            if current_item:
                items.append(current_item)
                current_item = None
        elif current_item and line.startswith('*') and '·' in line:
            parsed = _parse_source_line(line)
            if parsed:
                sources, date = parsed
                current_item['sources'] = sources
                current_item['date'] = date
        elif current_item and line and not line.startswith('#'):
            current_item['body'].append(line)

    if current_item:
        items.append(current_item)

    return items


def validate_item(
    item,
    articles,
    run_date,
    source_aliases,
    max_future_days: int = 1,
    stale_days: int = 2,
):
    """Validate one news item against verified articles."""
    violations = []

    cited_sources = item['sources']
    cited_date = item['date']
    cited_range = _SOURCE_DATES.parse_cited_date_range(cited_date) if cited_date else None
    cited_dt = cited_range[1] if cited_range else None

    # Check 1: Cited sources exist in verified articles and support this item
    article_sources = set()
    for article in articles:
        article_sources.update(_SOURCE_SUPPORT.article_source_values(article))

    has_fresh_aligned_support = False
    aligned_supporting_articles = []
    for src in cited_sources:
        src_lower = src.lower().strip()
        if any(x in src_lower for x in ['ai agent', '由 ', 'cst', '每日']):
            continue
        candidates = [
            article for article in articles
            if _SOURCE_SUPPORT.article_matches_source(article, src_lower, source_aliases)
        ]
        found = bool(candidates)
        if not found:
            violations.append(
                f"SOURCE: Cited source '{src}' not found in verified articles. "
                f"Available sources: {sorted(article_sources)[:10]}..."
            )
            continue

        if candidates:
            aligned_candidates = []
            for article in candidates:
                article_aligned, _overlap = _SOURCE_SUPPORT.item_article_alignment(item, article)
                if article_aligned:
                    aligned_candidates.append(article)
            if not aligned_candidates:
                violations.append(
                    f"SOURCE_CONTEXT: Cited source '{src}' exists, but no matching "
                    f"article from that source supports item '{item.get('title', '')[:60]}'."
                )
                continue
            aligned_supporting_articles.extend(aligned_candidates)
            if any(not _SOURCE_DATES.is_background_article(article) for article in aligned_candidates):
                has_fresh_aligned_support = True

            article_dates = [
                parsed
                for article in aligned_candidates
                if not _SOURCE_DATES.is_background_article(article)
                if (parsed := _SOURCE_DATES.parse_article_date(article)) is not None
            ]
            if cited_range and article_dates and all(
                not (cited_range[0].date() <= article_dt.date() <= cited_range[1].date())
                for article_dt in article_dates
            ) and all(
                min(
                    abs((article_dt.date() - cited_range[0].date()).days),
                    abs((article_dt.date() - cited_range[1].date()).days),
                ) > stale_days
                for article_dt in article_dates
            ):
                observed = sorted({article_dt.date().isoformat() for article_dt in article_dates})
                violations.append(
                    f"SOURCE_DATE: Cited source '{src}' supports the item, but its "
                    f"article date(s) {observed} do not match cited date "
                    f"'{cited_date}'."
                )

    if cited_sources and not has_fresh_aligned_support:
        violations.append(
            "SOURCE_CONTEXT: Item is supported only by background evidence; "
            "at least one fresh non-background source is required."
        )

    # Check 2: Date within 48h window
    if cited_date:
        try:
            item_date = cited_dt
            if not item_date:
                raise ValueError(cited_date)
            run_dt = datetime.fromisoformat(run_date).replace(tzinfo=CST)
            diff = (run_dt - item_date).days

            if diff < -max_future_days:
                violations.append(
                    f"DATE: '{cited_date}' is {-diff} days in the future "
                    f"(max {max_future_days} days)."
                )
            if diff > stale_days:
                violations.append(
                    f"DATE: '{cited_date}' is {diff} days old (max {stale_days} days)."
                )
        except (ValueError, AttributeError):
            violations.append(f"DATE: Cannot parse date '{cited_date}'")

    if not cited_sources:
        violations.append("SOURCE: No sources cited for this item")

    if not cited_date:
        violations.append("DATE: No date cited for this item")

    violations.extend(validate_overclaims(item, aligned_supporting_articles))

    return violations


def validate_briefing(
    markdown_text: str,
    items: list[dict],
    articles: list[dict],
    run_date: str,
    source_aliases: dict,
    *,
    pipeline_config: dict | None = None,
    max_future_days: int = 1,
    stale_days: int = 2,
    event_threads_path: str | None = None,
    schemas_dir: str | None = None,
) -> dict:
    """Validate a parsed briefing and return a structured report payload."""
    all_violations: list[tuple[int, str, list[str], dict]] = []
    boilerplate_violations = validate_boilerplate(markdown_text, pipeline_config or {})
    if boilerplate_violations:
        all_violations.append((
            0,
            "boilerplate",
            boilerplate_violations,
            {
                "kind": "boilerplate",
                "title": "boilerplate",
                "sources": [],
                "date": None,
            },
        ))

    for i, item in enumerate(items, 1):
        violations = validate_item(
            item,
            articles,
            run_date,
            source_aliases,
            max_future_days=max_future_days,
            stale_days=stale_days,
        )
        if violations:
            all_violations.append((
                i,
                item["title"][:60],
                violations,
                {
                    "kind": "item",
                    "title": item.get("title", ""),
                    "sources": list(item.get("sources") or []),
                    "date": item.get("date"),
                },
            ))

    if event_threads_path and schemas_dir:
        schema_violations = validate_structured_output(event_threads_path, schemas_dir)
        if schema_violations:
            all_violations.append((
                0,
                "structured_output",
                schema_violations,
                {
                    "kind": "structured_output",
                    "title": "structured_output",
                    "sources": [],
                    "date": None,
                },
            ))

    total_violations = sum(len(v) for _, _, v, _ in all_violations)
    item_entries = [entry for entry in all_violations if entry[3]["kind"] == "item"]
    payload = {
        "status": "ok" if total_violations == 0 else "violations",
        "items": len(items),
        "violations": total_violations,
        "summary": {
            "item_violations": sum(len(v) for _, _, v, meta in all_violations if meta["kind"] == "item"),
            "boilerplate_violations": len(boilerplate_violations),
            "structured_output_violations": sum(
                len(v) for _, _, v, meta in all_violations if meta["kind"] == "structured_output"
            ),
            "invalid_items": len(item_entries),
        },
        "details": [
            {
                "item": idx,
                "kind": meta["kind"],
                "title": meta["title"],
                "sources": meta["sources"],
                "date": meta["date"],
                "violations": v,
            }
            for idx, _label, v, meta in all_violations
        ],
    }
    return payload


def validate_schema_items(data: list, schema_path: str, item_type: str) -> list[str]:
    """Validate a list of items against a JSON Schema file."""
    if not data:
        return []
    with open(schema_path) as f:
        schema = json.load(f)
    violations = []
    for i, item in enumerate(data):
        try:
            json_validate(instance=item, schema=schema)
        except ValidationError as e:
            violations.append(
                f"SCHEMA_{item_type.upper()}: Item {i}: {e.message}"
            )
    return violations


def validate_structured_output(
    event_threads_path: str, schemas_dir: str
) -> list[str]:
    """Validate event-thread structured output against JSON Schemas."""
    if not os.path.exists(event_threads_path):
        return []

    with open(event_threads_path) as f:
        data = json.load(f)

    violations = []

    threads = data.get("threads", [])
    if threads:
        schema_path = os.path.join(schemas_dir, "event_thread.schema.json")
        if os.path.exists(schema_path):
            violations.extend(validate_schema_items(threads, schema_path, "thread"))
        else:
            violations.append(f"SCHEMA: event_thread schema not found at {schema_path}")

    causal_edges = data.get("causal_edges", [])
    if causal_edges:
        schema_path = os.path.join(schemas_dir, "causal_edge.schema.json")
        if os.path.exists(schema_path):
            violations.extend(
                validate_schema_items(causal_edges, schema_path, "causal_edge")
            )
        else:
            violations.append(f"SCHEMA: causal_edge schema not found at {schema_path}")

    judgments = data.get("judgments", [])
    if judgments:
        schema_path = os.path.join(schemas_dir, "judgment.schema.json")
        if os.path.exists(schema_path):
            violations.extend(
                validate_schema_items(judgments, schema_path, "judgment")
            )
        else:
            violations.append(f"SCHEMA: judgment schema not found at {schema_path}")

    return violations


def main():
    parser = argparse.ArgumentParser(description="Validate briefing against verified articles")
    parser.add_argument("--md", "-m", required=True, help="Briefing markdown file")
    parser.add_argument("--articles", "-a", required=True, help="Articles JSONL file")
    parser.add_argument("--date", "-d", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--domain", required=True, help="Path to domain.yaml")
    parser.add_argument("--stale-days", type=int,
                        help="Override domain stale date window, usually from the search window")
    parser.add_argument("--event-threads", help="Path to event-threads.json (structured output)")
    parser.add_argument("--schemas-dir", help="Path to _schemas/ directory for JSON Schema validation")
    parser.add_argument("--output-report", help="Optional path to write structured validate_report.json")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)
    source_aliases = pipeline_config.get("source_aliases", {})
    max_future_days, stale_days = resolve_date_window(pipeline_config, args.stale_days)

    articles = load_articles(args.articles)
    items = parse_markdown(args.md)
    with open(args.md) as f:
        markdown_text = f.read()

    print(f"\n📋 Validating briefing: {len(items)} news items against {len(articles)} articles",
          file=sys.stderr)

    payload = validate_briefing(
        markdown_text,
        items,
        articles,
        args.date,
        source_aliases,
        pipeline_config=pipeline_config,
        max_future_days=max_future_days,
        stale_days=stale_days,
        event_threads_path=args.event_threads,
        schemas_dir=args.schemas_dir,
    )

    detail_map = {
        (detail["item"], detail["kind"], detail["title"]): detail["violations"]
        for detail in payload["details"]
    }
    if payload["summary"]["boilerplate_violations"]:
        print(f"\n  ❌ Boilerplate leaks: {payload['summary']['boilerplate_violations']}", file=sys.stderr)
        for violation in detail_map.get((0, "boilerplate", "boilerplate"), [])[:10]:
            print(f"     {violation}", file=sys.stderr)

    for i, item in enumerate(items, 1):
        violations = detail_map.get((i, "item", item.get("title", "")), [])
        if violations:
            print(f"\n  ❌ Item {i}: {item['title'][:60]}", file=sys.stderr)
            for v in violations:
                print(f"     {v}", file=sys.stderr)
        else:
            print(f"  ✅ Item {i}: {item['title'][:60]}", file=sys.stderr)

    if payload["summary"]["structured_output_violations"]:
        print(f"\n  🔍 Schema validation:", file=sys.stderr)
        for violation in detail_map.get((0, "structured_output", "structured_output"), []):
            print(f"     {violation}", file=sys.stderr)

    total_violations = payload["violations"]

    print(f"\n{'='*60}", file=sys.stderr)
    if total_violations == 0:
        print(f"  ✅ ALL {len(items)} ITEMS VALID — no violations", file=sys.stderr)
    else:
        print(
            f"  ❌ {total_violations} VIOLATIONS in {payload['summary']['invalid_items'] + bool(payload['summary']['boilerplate_violations']) + bool(payload['summary']['structured_output_violations'])} items",
            file=sys.stderr,
        )
    print(f"{'='*60}\n", file=sys.stderr)

    if args.output_report:
        with open(args.output_report, "w") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    print(json.dumps(payload))

    sys.exit(0 if total_violations == 0 else 1)


if __name__ == "__main__":
    main()
