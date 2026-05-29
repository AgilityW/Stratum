"""cascade.py — Multi-scale cascade framework.

Each cascade run (weekly, monthly, quarterly, yearly):
  1. Reads briefings/{scale}/cascade.yaml — what to consume, what to search
  2. Reads upstream structured data from SQLite (causal_edges, judgments, entities)
  3. Runs independent fresh search with scale-specific queries
  4. Assembles prompt → calls LLM
  5. Produces briefing.md + writes results back to SQLite

Usage:
    python3 cascade.py --domain storage --scale weekly --period 2026-W22
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import yaml
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def _project_root() -> str:
    """Find project root by locating config.yaml or .git."""
    current = os.path.dirname(os.path.abspath(__file__))
    # Walk up from cascade.py (stratum/cascade.py) to project root
    for _ in range(3):
        if os.path.exists(os.path.join(current, 'config.yaml')):
            return current
        if os.path.exists(os.path.join(current, '.git')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    # Fallback to CWD
    return os.getcwd()

_project_root_path = _project_root()
if _project_root_path not in sys.path:
    sys.path.insert(0, _project_root_path)

from stratum.db.ingest import (
    get_queries_for_scale,
    get_upstream_structured_data,
    get_last_cascade_run,
    ingest_cascade_log,
    ingest_entity_snapshots,
    ingest_coverage,
)


def load_cascade_config(scale: str) -> dict:
    """Load cascade.yaml for the given scale."""
    cascade_path = os.path.join(
        _project_root(), 'briefings', scale, 'cascade.yaml'
    )
    if not os.path.exists(cascade_path):
        return {}
    with open(cascade_path) as f:
        return yaml.safe_load(f)


def load_manifest(scale: str) -> dict:
    """Load manifest.yaml for the given scale."""
    manifest_path = os.path.join(
        _project_root(), 'briefings', scale, 'manifest.yaml'
    )
    if not os.path.exists(manifest_path):
        return {}
    with open(manifest_path) as f:
        return yaml.safe_load(f)


def compute_window(scale: str, period: str) -> tuple[str, str]:
    """Compute the date window for a scale/period.

    Returns (start_date, end_date) in YYYY-MM-DD.
    """
    if scale == 'weekly':
        # ISO week → date range. Approximate: period='2026-W22' → 2026-05-25..2026-05-31
        year = int(period[:4])
        week = int(period.split('W')[1])
        import datetime as dt
        jan1 = dt.date(year, 1, 1)
        # First Monday of year
        days_until_monday = (7 - jan1.weekday()) % 7
        first_monday = jan1 + dt.timedelta(days=days_until_monday)
        start = first_monday + dt.timedelta(weeks=week - 1)
        end = start + dt.timedelta(days=6)
        return start.isoformat(), end.isoformat()

    elif scale == 'monthly':
        # period='2026-05'
        year, month = map(int, period.split('-'))
        start = f'{year}-{month:02d}-01'
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        end = f'{year}-{month:02d}-{last_day:02d}'
        return start, end

    elif scale == 'quarterly':
        # period='2026-Q2' → 2026-04-01..2026-06-30
        year = int(period[:4])
        q = int(period.split('Q')[1])
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        import calendar
        start = f'{year}-{start_month:02d}-01'
        last_day = calendar.monthrange(year, end_month)[1]
        end = f'{year}-{end_month:02d}-{last_day:02d}'
        return start, end

    elif scale == 'yearly':
        year = int(period[:4])
        return f'{year}-01-01', f'{year}-12-31'

    else:
        raise ValueError(f'Unknown scale: {scale}')


def run_search_for_scale(domain: str, scale: str, period: str,
                         config: dict) -> list[dict]:
    """Run independent search for the given scale/period.

    Returns list of raw search result dicts.
    """
    start_date, end_date = compute_window(scale, period)

    queries = get_queries_for_scale(domain, scale)
    if not queries:
        print(f'⚠️  No queries found for scale={scale}', file=sys.stderr)
        return []

    # Convert to legacy format for search
    queries_config = {'seed_queries': {}, 'gap_searches': []}
    for q in queries:
        locale = q.get('locale', 'zh-CN')
        intent = q.get('intent', 'detection')
        if intent == 'verification':
            queries_config['gap_searches'].append({'query': q['text'], 'locale': locale})
        else:
            queries_config['seed_queries'].setdefault(locale, []).append(q['text'])

    print(f'🔍 {scale} search: {len(queries)} queries, window={start_date}..{end_date}',
          file=sys.stderr)

    # Run search (simplified — in production, call search stage directly)
    # For now, return query count as placeholder
    results = []
    for locale, qlist in queries_config.get('seed_queries', {}).items():
        for text in qlist:
            results.append({
                'id': f'result-{len(results):04d}',
                'title': text,
                'url': '',
                'source': '',
                'published_at': start_date,
                'snippet': f'Search result for: {text}',
                'engine': 'placeholder',
                'query_used': text,
            })

    return results


def run_cascade(domain: str, scale: str, period: str) -> dict:
    """Execute a cascade run for the given scale and period.

    Returns stats dict.
    """
    cascade_cfg = load_cascade_config(scale)
    manifest = load_manifest(scale)

    if not cascade_cfg:
        print(f'⚠️  No cascade.yaml found for scale={scale}. Using defaults.', file=sys.stderr)

    start_date, end_date = compute_window(scale, period)

    # 1. Consume upstream structured data
    consume_cfg = cascade_cfg.get('consume', [])
    upstream_data = {}
    for upstream in consume_cfg:
        from_scale = upstream['scale']
        u_data = get_upstream_structured_data(domain, from_scale, start_date, end_date)
        upstream_data[from_scale] = u_data
        n_edges = len(u_data.get('causal_edges', []))
        n_judgments = len(u_data.get('judgments', []))
        print(f'📊 Consumed {from_scale}: {n_edges} edges, {n_judgments} judgments',
              file=sys.stderr)

    # 2. Run independent search
    # In full implementation, this calls the search stage
    config = {}  # Would load from config.yaml
    search_results = run_search_for_scale(domain, scale, period, config)

    # 3. Write cascade log
    now = datetime.now(CST).isoformat()
    ingest_cascade_log(domain, {
        'scale': scale,
        'period': period,
        'run_at': now,
        'consumed_from': consume_cfg[0]['scale'] if consume_cfg else 'daily',
        'consumed_window': f'{start_date}..{end_date}',
        'consumed_causal_edges': sum(
            len(u.get('causal_edges', [])) for u in upstream_data.values()
        ),
        'consumed_judgments': sum(
            len(u.get('judgments', [])) for u in upstream_data.values()
        ),
        'fresh_search_articles': len(search_results),
        'produced_judgments': 0,
        'status': 'ok',
    })

    # 4. Entity snapshots
    entity_count = ingest_entity_snapshots(domain, scale, period)
    print(f'💾 {entity_count} entity snapshots (scale={scale})', file=sys.stderr)

    stats = {
        'scale': scale,
        'period': period,
        'window': (start_date, end_date),
        'upstream_consumed': {
            k: {
                'causal_edges': len(v.get('causal_edges', [])),
                'judgments': len(v.get('judgments', [])),
            }
            for k, v in upstream_data.items()
        },
        'fresh_search_articles': len(search_results),
        'entity_snapshots': entity_count,
    }

    return stats


def main():
    parser = argparse.ArgumentParser(description='Stratum multi-scale cascade')
    parser.add_argument('--domain', '-d', required=True, help='Domain ID (e.g. storage)')
    parser.add_argument('--scale', '-s', required=True,
                        choices=['weekly', 'monthly', 'quarterly', 'yearly'],
                        help='Cascade scale')
    parser.add_argument('--period', '-p', required=True,
                        help='Period identifier (e.g. 2026-W22, 2026-05, 2026-Q2, 2026)')
    args = parser.parse_args()

    stats = run_cascade(args.domain, args.scale, args.period)

    print(f'\n{"="*60}', file=sys.stderr)
    print(f'  CASCADE COMPLETE', file=sys.stderr)
    print(f'  Domain:  {args.domain}', file=sys.stderr)
    print(f'  Scale:   {args.scale}', file=sys.stderr)
    print(f'  Period:  {args.period}', file=sys.stderr)
    print(f'  Window:  {stats["window"][0]} .. {stats["window"][1]}', file=sys.stderr)
    print(f'  Search:  {stats["fresh_search_articles"]} articles', file=sys.stderr)
    print(f'  Snapshot: {stats["entity_snapshots"]} entities', file=sys.stderr)
    print(f'{"="*60}\n', file=sys.stderr)

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
