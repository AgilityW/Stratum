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
from urllib.parse import urlparse

from stratum.subsystems.search.models import source_pattern_matches

CST = timezone(timedelta(hours=8))


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


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    return host


def _article_source_values(article: dict) -> list[str]:
    """Return all source-like values a pipeline article may carry."""
    values = [
        article.get("source", ""),
        article.get("source_domain", ""),
        _domain_from_url(article.get("url", "")),
    ]
    return [v.strip().lower() for v in values if v and v.strip()]


_TOKEN_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "will", "said",
    "update", "market", "prices", "price", "news", "report", "reports",
    "announced", "announces", "company", "industry", "memory",
}


def _content_tokens(text: str) -> set[str]:
    """Extract coarse multilingual content tokens for item/article alignment."""
    tokens: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]*|[\u4e00-\u9fff]{2,}", text.lower()):
        token = token.strip(".-")
        if len(token) < 2 or token in _TOKEN_STOPWORDS:
            continue
        tokens.add(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            for size in (2, 3, 4):
                for i in range(len(token) - size + 1):
                    tokens.add(token[i:i + size])
    return tokens


def _article_matches_source(article: dict, src_lower: str, source_aliases: dict) -> bool:
    """Return True if a cited source label maps to the article source."""
    article_sources = _article_source_values(article)
    alias_patterns = _source_alias_patterns(source_aliases.get(src_lower))
    if alias_patterns:
        if any(
            _source_value_matches_pattern(asrc, pattern)
            for pattern in alias_patterns
            for asrc in article_sources
        ):
            return True
    if _looks_like_domain_label(src_lower):
        return any(_source_value_matches_pattern(asrc, src_lower) for asrc in article_sources)
    return src_lower in article_sources


def _source_alias_patterns(alias_value) -> list[str]:
    """Normalize source alias config to a list of domain patterns."""
    if not alias_value:
        return []
    if isinstance(alias_value, str):
        values = [alias_value]
    elif isinstance(alias_value, (list, tuple, set)):
        values = alias_value
    else:
        return []
    return [str(value).strip().lower() for value in values if str(value).strip()]


def _source_value_matches_pattern(source_value: str, pattern: str) -> bool:
    """Match source/domain values using URL host boundaries."""
    source_value = (source_value or "").strip().lower()
    pattern = (pattern or "").strip().lower()
    if not source_value or not pattern:
        return False
    return source_pattern_matches(f"https://{source_value}", pattern)


def _looks_like_domain_label(source_label: str) -> bool:
    """Return True when the cited source is domain-like rather than a brand name."""
    value = source_label.strip().lower()
    return "." in value or value.startswith(("www.", "m."))


def _item_article_alignment(item: dict, article: dict) -> tuple[bool, set[str]]:
    """Check whether a cited source article plausibly supports the news item."""
    item_text = f"{item.get('title', '')} {' '.join(item.get('body', []))}"
    article_text = (
        f"{article.get('title', '')} "
        f"{article.get('snippet', '')} "
        f"{article.get('extracted_summary', '')}"
    )
    item_tokens = _content_tokens(item_text)
    article_tokens = _content_tokens(article_text)
    if not item_tokens:
        return True, set()
    if not article_tokens:
        return False, set()

    overlap = item_tokens & article_tokens
    if any(_is_strong_alignment_token(token) for token in overlap):
        return True, overlap
    if len(overlap) >= 2:
        return True, overlap
    if overlap and len(overlap) / max(1, min(len(item_tokens), len(article_tokens))) >= 0.34:
        return True, overlap
    return False, overlap


def _is_strong_alignment_token(token: str) -> bool:
    """Return True for distinctive product/technology tokens such as HBM4E."""
    token = token.strip().lower()
    if len(token) < 4:
        return False
    if not re.search(r"[a-z]", token) or not re.search(r"\d", token):
        return False
    return token not in _TOKEN_STOPWORDS


def _parse_cited_date_range(cited_date: str) -> tuple[datetime, datetime] | None:
    """Parse Chinese or ISO-ish source dates, including same-month ranges."""
    cn_range = re.search(
        r'(\d{4})年(\d{1,2})月(\d{1,2})\s*(?:-|~|至|到)\s*(\d{1,2})日',
        cited_date,
    )
    if cn_range:
        y, m, start_d, end_d = map(int, cn_range.groups())
        start = datetime(y, m, start_d).replace(tzinfo=CST)
        end = datetime(y, m, end_d).replace(tzinfo=CST)
        return (start, end) if start <= end else (end, start)

    cn_full_range = re.search(
        r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*(?:-|~|至|到)\s*'
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',
        cited_date,
    )
    if cn_full_range:
        y1, m1, d1, y2, m2, d2 = map(int, cn_full_range.groups())
        start = datetime(y1, m1, d1).replace(tzinfo=CST)
        end = datetime(y2, m2, d2).replace(tzinfo=CST)
        return (start, end) if start <= end else (end, start)

    iso_range = re.search(
        r'(\d{4}-\d{2}-\d{2})\s*(?:/|-|~|至|到)\s*(\d{4}-\d{2}-\d{2})',
        cited_date,
    )
    if iso_range:
        start = datetime.fromisoformat(iso_range.group(1)).replace(tzinfo=CST)
        end = datetime.fromisoformat(iso_range.group(2)).replace(tzinfo=CST)
        return (start, end) if start <= end else (end, start)

    single = _parse_cited_date(cited_date)
    if single:
        return single, single
    return None


def _parse_cited_date(cited_date: str) -> datetime | None:
    """Parse a single Chinese or ISO-ish date from briefing source lines."""
    cn_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', cited_date)
    if cn_match:
        y, m, d = map(int, cn_match.groups())
        return datetime(y, m, d).replace(tzinfo=CST)

    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', cited_date)
    if iso_match:
        return datetime.fromisoformat(iso_match.group(1)).replace(tzinfo=CST)

    return None


def _parse_article_date(article: dict) -> datetime | None:
    """Parse the best available publication date from an article record."""
    raw_date = (
        article.get("published_at")
        or article.get("datePublished")
        or article.get("date")
        or ""
    )
    if not raw_date:
        return None

    text = str(raw_date).strip()
    cn_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if cn_match:
        y, m, d = map(int, cn_match.groups())
        return datetime(y, m, d).replace(tzinfo=CST)

    iso_text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_text).astimezone(CST)
    except ValueError:
        iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if iso_match:
            return datetime.fromisoformat(iso_match.group(1)).replace(tzinfo=CST)
    return None


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
    cited_range = _parse_cited_date_range(cited_date) if cited_date else None
    cited_dt = cited_range[1] if cited_range else None

    # Check 1: Cited sources exist in verified articles and support this item
    article_sources = set()
    for article in articles:
        article_sources.update(_article_source_values(article))

    for src in cited_sources:
        src_lower = src.lower().strip()
        if any(x in src_lower for x in ['ai agent', '由 ', 'cst', '每日']):
            continue
        candidates = [
            article for article in articles
            if _article_matches_source(article, src_lower, source_aliases)
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
                article_aligned, _overlap = _item_article_alignment(item, article)
                if article_aligned:
                    aligned_candidates.append(article)
            if not aligned_candidates:
                violations.append(
                    f"SOURCE_CONTEXT: Cited source '{src}' exists, but no matching "
                    f"article from that source supports item '{item.get('title', '')[:60]}'."
                )
                continue

            article_dates = [
                parsed
                for article in aligned_candidates
                if (parsed := _parse_article_date(article)) is not None
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
    parser.add_argument("--event-threads", help="Path to event-threads.json (structured output)")
    parser.add_argument("--schemas-dir", help="Path to _schemas/ directory for JSON Schema validation")
    args = parser.parse_args()

    pipeline_config = load_domain_config(args.domain)
    source_aliases = pipeline_config.get("source_aliases", {})
    date_window = pipeline_config.get("date_window", {})
    max_future_days = int(date_window.get("max_future_days", 1))
    stale_days = int(date_window.get("stale_days", 2))

    articles = load_articles(args.articles)
    items = parse_markdown(args.md)

    print(f"\n📋 Validating briefing: {len(items)} news items against {len(articles)} articles",
          file=sys.stderr)

    all_violations = []
    for i, item in enumerate(items, 1):
        violations = validate_item(
            item,
            articles,
            args.date,
            source_aliases,
            max_future_days=max_future_days,
            stale_days=stale_days,
        )
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
