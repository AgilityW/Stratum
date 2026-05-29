#!/usr/bin/env python3
"""validate.py — Content gate: verify briefing .md claims trace back to verified articles.

Domain-agnostic. Source aliases loaded from domain.yaml.

Input:  briefing.md (LLM-written markdown) + articles.jsonl (verified/normalized articles)
Output: JSON to stdout — {status: "ok"|"violations", items, violations, details}
Side effects: None. Reads files, writes nothing except stderr logs.
Invariants:  Every cited source in .md must match a domain in articles.jsonl.
             Every cited date must be within 48h of run_date.
Error behavior: Source mismatch → SOURCE violation. Stale date → DATE violation.
                Missing source/date → flagged. Exit code 0 if clean, 1 if violations.

Usage:
    python3 validate.py --md briefing.md --articles articles.jsonl \
        --date 2026-05-28 --domain domains/storage/domain.yaml
"""
import argparse
import json
import os
import re
import sys
import yaml
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from jsonschema import validate as json_validate, ValidationError

CST = timezone(timedelta(hours=8))
TITLE_SIMILARITY_THRESHOLD = 0.22


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


def parse_markdown(path):
    """Parse briefing .md into structured sections."""
    with open(path) as f:
        content = f.read()

    items = []
    current_item = None

    for line in content.split('\n'):
        line = line.strip()

        if line.startswith('### ') and '今日要点' not in line and '关注' not in line and '反向信号' not in line:
            if current_item:
                items.append(current_item)
            current_item = {
                'title': line.replace('### ', '').strip(),
                'body': [],
                'sources': [],
                'date': None,
            }
        elif current_item and line.startswith('*') and '·' in line:
            source_line = line.strip('* ')
            parts = source_line.split('·')
            if len(parts) >= 2:
                sources_part = parts[0].strip()
                date_part = parts[-1].strip()
                current_item['sources'] = [s.strip() for s in sources_part.split(',')]
                current_item['date'] = date_part
        elif current_item and line and not line.startswith('#'):
            current_item['body'].append(line)

    if current_item:
        items.append(current_item)

    return items


def validate_item(item, articles, run_date, source_aliases):
    """Validate one news item against verified articles."""
    violations = []

    cited_sources = item['sources']
    cited_date = item['date']

    # Check 1: Cited sources exist in verified articles
    article_sources = {a.get('source', '') for a in articles}
    article_domains = set()
    for s in article_sources:
        for part in s.split('.'):
            if len(part) > 2:
                article_domains.add(part.lower())

    for src in cited_sources:
        src_lower = src.lower().strip()
        if any(x in src_lower for x in ['ai agent', '由 ', 'cst', '每日']):
            continue
        found = False
        alias_match = source_aliases.get(src_lower)
        if alias_match:
            for asrc in article_sources:
                if alias_match in asrc.lower():
                    found = True
                    break
        if not found:
            for asrc in article_sources:
                if src_lower in asrc.lower() or asrc.lower() in src_lower:
                    found = True
                    break
        if not found:
            for domain in article_domains:
                if domain in src_lower or src_lower in domain:
                    found = True
                    break
        if not found:
            violations.append(
                f"SOURCE: Cited source '{src}' not found in verified articles. "
                f"Available sources: {sorted(article_sources)[:10]}..."
            )

    # Check 2: Date within 48h window
    if cited_date:
        try:
            date_match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', cited_date)
            if date_match:
                y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                item_date = datetime(y, m, d).replace(tzinfo=CST)
                run_dt = datetime.fromisoformat(run_date).replace(tzinfo=CST)
                diff = (run_dt - item_date).days

                if diff > 2:
                    violations.append(
                        f"DATE: '{cited_date}' is {diff} days old (max 2 days)."
                    )
        except (ValueError, AttributeError):
            violations.append(f"DATE: Cannot parse date '{cited_date}'")

    if not cited_sources:
        violations.append("SOURCE: No sources cited for this item")

    if not cited_date:
        violations.append("DATE: No date cited for this item")

    return violations


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
    """Validate causal_edges and judgments against their JSON Schemas."""
    if not os.path.exists(event_threads_path):
        return []

    with open(event_threads_path) as f:
        data = json.load(f)

    violations = []

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
    parser.add_argument("--event-threads", help="Path to event-threads.json (structured output)")
    parser.add_argument("--schemas-dir", help="Path to _schemas/ directory for JSON Schema validation")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)
    source_aliases = pipeline_config.get("source_aliases", {})

    articles = load_articles(args.articles)
    items = parse_markdown(args.md)

    print(f"\n📋 Validating briefing: {len(items)} news items against {len(articles)} articles",
          file=sys.stderr)

    all_violations = []
    for i, item in enumerate(items, 1):
        violations = validate_item(item, articles, args.date, source_aliases)
        if violations:
            all_violations.append((i, item['title'][:60], violations))
            print(f"\n  ❌ Item {i}: {item['title'][:60]}", file=sys.stderr)
            for v in violations:
                print(f"     {v}", file=sys.stderr)
        else:
            print(f"  ✅ Item {i}: {item['title'][:60]}", file=sys.stderr)

    # ── Schema validation (structured output) ──
    if args.event_threads and args.schemas_dir:
        schema_violations = validate_structured_output(
            args.event_threads, args.schemas_dir
        )
        if schema_violations:
            all_violations.append((0, "structured_output", schema_violations))
            print(f"\n  🔍 Schema validation:", file=sys.stderr)
            for v in schema_violations:
                print(f"     {v}", file=sys.stderr)

    total_violations = sum(len(v) for _, _, v in all_violations)

    print(f"\n{'='*60}", file=sys.stderr)
    if total_violations == 0:
        print(f"  ✅ ALL {len(items)} ITEMS VALID — no violations", file=sys.stderr)
    else:
        print(f"  ❌ {total_violations} VIOLATIONS in {len(all_violations)} items", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    print(json.dumps({
        "status": "ok" if total_violations == 0 else "violations",
        "items": len(items),
        "violations": total_violations,
        "details": [
            {"item": idx, "violations": v}
            for idx, _, v in all_violations
        ],
    }))

    sys.exit(0 if total_violations == 0 else 1)


if __name__ == "__main__":
    main()
