#!/usr/bin/env python3
"""search.py — Deterministic search stage: calls search engines directly via API.

Replaces the LLM-driven Agent Search placeholder.
Reads engine configs from config.yaml, queries from domains/{domain}/queries.yaml.
Calls each engine's API with precise date-range filters, maps response fields to
Stratum raw.json schema, and deduplicates by URL.

Date semantics:
  - Bocha:   freshness="YYYY-MM-DD..YYYY-MM-DD" — precise range filter
  - Tavily:  start_date + end_date — precise range filter
  - Both engines return per-result dates (datePublished / published_date)
  - _normalize_date handles ISO (bocha) and HTTP-date (tavily) formats

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
import subprocess
import sys
import yaml
from datetime import datetime
from urllib.parse import urlparse

# ── Constants ──

RESULTS_PER_QUERY = 5
REQUEST_TIMEOUT = 12


def load_config(config_path: str) -> dict:
    """Load config.yaml, resolving ${VAR} references from environment and .env file."""
    # Read .env from project root if it exists (gitignored, user-provided)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val

    with open(config_path) as f:
        raw = f.read()
    # Resolve ${VAR} references from environment
    for match in re.finditer(r'\$\{(\w+)\}', raw):
        var_name = match.group(1)
        env_val = os.environ.get(var_name, "")
        raw = raw.replace(match.group(0), env_val)
    return yaml.safe_load(raw)


def load_queries(queries_path: str, run_date: str) -> dict:
    """Load queries.yaml and resolve placeholders like ${CURRENT_YEAR}."""
    with open(queries_path) as f:
        raw = f.read()

    dt = datetime.fromisoformat(run_date)
    replacements = {
        "${CURRENT_YEAR}": str(dt.year),
        "${CURRENT_MONTH_EN}": dt.strftime("%B"),
        "${CURRENT_MONTH_ZH}": f"{dt.month}月",
    }
    for placeholder, value in replacements.items():
        raw = raw.replace(placeholder, value)

    return yaml.safe_load(raw)


def call_bocha(query: str, count: int, run_date: str, api_key: str) -> list[dict]:
    """Call Bocha AI search API with precise date range. Returns normalized results.

    Bocha freshness supports "YYYY-MM-DD..YYYY-MM-DD" for exact-day filtering.
    """
    freshness = f"{run_date}..{run_date}"
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "https://api.bocha.cn/v1/web-search",
             "-H", f"Authorization: Bearer {api_key}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({
                 "query": query,
                 "count": count,
                 "freshness": freshness,
             })],
            capture_output=True, text=True, timeout=REQUEST_TIMEOUT,
        )
        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)
        pages = data.get("data", {}).get("webPages", {}).get("value", [])

        results = []
        for p in pages:
            results.append({
                "title": p.get("name", ""),
                "url": p.get("url", ""),
                "snippet": p.get("snippet", ""),
                "description": p.get("snippet", ""),
                "datePublished": _normalize_date(p.get("datePublished", "")),
                "engine": "bocha",
                "query_used": query,
            })
        return results
    except Exception as e:
        print(f"  ⚠️  bocha error for '{query[:40]}': {e}", file=sys.stderr)
        return []


def call_tavily(query: str, count: int, run_date: str, api_key: str) -> list[dict]:
    """Call Tavily search API with precise date range. Returns normalized results.

    Uses start_date + end_date (YYYY-MM-DD) for exact-day filtering.
    Tavily returns published_date in HTTP format (Thu, 28 May 2026 15:02:21 GMT).
    """
    if not api_key:
        return []
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "https://api.tavily.com/search",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({
                 "api_key": api_key,
                 "query": query,
                 "max_results": count,
                 "search_depth": "advanced",
                 "topic": "news",
                 "start_date": run_date,
                 "end_date": run_date,
             })],
            capture_output=True, text=True, timeout=REQUEST_TIMEOUT,
        )
        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)
        items = data.get("results", [])

        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "description": item.get("content", ""),
                "datePublished": _normalize_date(item.get("published_date", "")),
                "engine": "tavily",
                "query_used": query,
            })
        return results
    except Exception as e:
        print(f"  ⚠️  tavily error for '{query[:40]}': {e}", file=sys.stderr)
        return []


# ── Date normalization ──

# Month name → number for HTTP date parsing
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# HTTP date: Thu, 28 May 2026 15:02:21 GMT
_HTTP_DATE_RE = re.compile(
    r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
    re.IGNORECASE,
)


def _normalize_date(date_str: str) -> str:
    """Normalize date to YYYY-MM-DD.

    Handles:
      - ISO:     2026-05-29T00:00:00+08:00 → 2026-05-29
      - HTTP:    Thu, 28 May 2026 15:02:21 GMT → 2026-05-28
    """
    if not date_str:
        return ""
    date_str = date_str.strip()

    # ISO format: YYYY-MM-DD at start
    m = re.match(r'(\d{4}-\d{2}-\d{2})', date_str)
    if m:
        return m.group(1)

    # HTTP date format: "Thu, 28 May 2026 ..."
    m = _HTTP_DATE_RE.search(date_str)
    if m:
        day = m.group(1).zfill(2)
        month = str(_MONTH_MAP.get(m.group(2)[:3].lower(), 1)).zfill(2)
        year = m.group(3)
        return f"{year}-{month}-{day}"

    return ""


def run_search(config: dict, queries_config: dict, domain_id: str, *, date: str) -> list[dict]:
    """Execute all queries across locales, deduplicate, return raw results."""
    engines = config.get("engines", {})
    bocha_key = engines.get("bocha", {}).get("auth", "").replace("Bearer ", "")
    tavily_key = engines.get("tavily", {}).get("auth", "").replace("api_key: ", "")

    all_results = []
    seen_urls = set()
    total_queries = 0

    seed_queries = queries_config.get("seed_queries", {})

    for locale, queries in seed_queries.items():
        # Route to engine based on locale
        engine = _engine_for_locale(locale, engines)
        if not engine:
            continue

        for query in queries:
            total_queries += 1
            count = RESULTS_PER_QUERY

            if engine == "bocha" and bocha_key:
                results = call_bocha(query, count, date, bocha_key)
            elif engine == "tavily" and tavily_key:
                results = call_tavily(query, count, date, tavily_key)
            else:
                results = []

            for r in results:
                url = _normalize_url(r.get("url", ""))
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)

    print(f"\n📊 Search complete: {total_queries} queries → {len(all_results)} unique results",
          file=sys.stderr)
    return all_results


def _engine_for_locale(locale: str, engines: dict) -> str | None:
    """Find the engine configured for a given locale."""
    for engine_name, engine_cfg in engines.items():
        engine_langs = engine_cfg.get("languages", [])
        if locale in engine_langs:
            return engine_name
    return None


def _normalize_url(url: str) -> str:
    """Normalize URL for dedup: lowercase host, strip trailing slash + fragments."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{host}{path}"
    except Exception:
        return url.lower().strip().rstrip("/")


def main():
    parser = argparse.ArgumentParser(
        description="Deterministic search — calls search engines via API")
    parser.add_argument("--domain", "-d", required=True, help="Domain ID (e.g. 'storage')")
    parser.add_argument("--date", required=True, help="Run date YYYY-MM-DD")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--queries", help="Path to queries.yaml (ignored if --db is set)")
    parser.add_argument("--output", "-o", required=True, help="Output raw.json path")
    parser.add_argument("--stats", help="Output stats.json path (default: raw.stats.json)")
    parser.add_argument("--db", help="Path to SQLite database (overrides --queries)")
    parser.add_argument("--v1", action="store_true", help="Use legacy search (default: subsystem)")
    args = parser.parse_args()

    # ── Resolve workspace (project root where config.yaml lives) ──
    workspace = os.path.dirname(os.path.abspath(args.config))

    if not args.v1:
        _run_with_subsystem(args, workspace)
    else:
        _run_legacy(args)


def _run_with_subsystem(args, workspace: str):
    """Search via stratum.subsystems.search."""
    from stratum.subsystems.search import run_search, load_search_config, load_api_keys

    # Load queries (from DB or YAML)
    if args.db and os.path.exists(args.db):
        import sys as _sys
        _project_root = workspace
        if _project_root not in _sys.path:
            _sys.path.insert(0, _project_root)
        from stratum.db.ingest import get_queries_for_scale
        db_queries = get_queries_for_scale(args.domain, 'daily')
        queries = [{"id": q.get("id", ""), "text": q["text"], "locale": q.get("locale", "en"),
                    "intent": q.get("intent", "detection")} for q in db_queries]
    elif args.queries:
        queries = load_queries_flat(args.queries, args.date)
    else:
        print('❌ Either --queries or --db is required', file=sys.stderr)
        sys.exit(1)

    print(f'Searching with {len(queries)} queries...', file=sys.stderr)

    config = load_search_config(args.domain, workspace)
    api_keys = load_api_keys()
    result_set = run_search(queries, config, api_keys, args.date)

    # Write raw.json
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result_set.to_raw_json(), f, ensure_ascii=False, indent=2)

    # Write stats
    stats_path = args.stats or args.output.replace(".json", ".stats.json")
    with open(stats_path, "w") as f:
        json.dump(result_set.to_stats_json(), f, ensure_ascii=False, indent=2)

    print(f"✅ Search: {result_set.total_curated} curated (from {result_set.total_raw} raw) → {args.output}",
          file=sys.stderr)


def load_queries_flat(queries_path: str, run_date: str) -> list[dict]:
    """Load queries.yaml and flatten to list format for subsystem."""
    import yaml
    from datetime import datetime
    with open(queries_path) as f:
        data = yaml.safe_load(f)

    dt = datetime.fromisoformat(run_date)
    subs = {
        "${CURRENT_YEAR}": str(dt.year),
        "${CURRENT_MONTH_EN}": dt.strftime("%B"),
        "${CURRENT_MONTH_ZH}": f"{dt.month}月",
    }

    queries = []
    seed = data.get("seed_queries", data.get("queries", {}))
    if isinstance(seed, list):
        for i, q in enumerate(seed):
            text = q.get("text", q.get("query", ""))
            for k, v in subs.items():
                text = text.replace(k, v)
            queries.append({"id": q.get("id", f"q-{i}"), "text": text,
                           "locale": q.get("locale", "en"), "intent": q.get("intent", "detection")})
    elif isinstance(seed, dict):
        for locale, qs in seed.items():
            for i, text in enumerate(qs):
                for k, v in subs.items():
                    text = text.replace(k, v)
                queries.append({"id": f"q-{locale}-{i}", "text": text,
                               "locale": locale, "intent": "detection"})

    return queries


def _run_legacy(args):
    """Legacy search — kept for fallback."""
    config = load_config(args.config)

    if args.db and os.path.exists(args.db):
        import sys as _sys
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if _project_root not in _sys.path:
            _sys.path.insert(0, _project_root)
        from stratum.db.ingest import get_queries_for_scale
        db_queries = get_queries_for_scale(args.domain, 'daily')
        queries_config = {'seed_queries': {}, 'gap_searches': []}
        for q in db_queries:
            locale = q.get('locale', 'zh-CN')
            intent = q.get('intent', 'detection')
            if intent == 'verification':
                queries_config['gap_searches'].append({'query': q['text'], 'locale': locale})
            else:
                queries_config['seed_queries'].setdefault(locale, []).append(q['text'])
        print(f'📋 Loaded {len(db_queries)} queries from DB', file=sys.stderr)
    elif args.queries:
        queries_config = load_queries(args.queries, args.date)
    else:
        print('❌ Either --queries or --db is required', file=sys.stderr)
        sys.exit(1)

    results = run_search(config, queries_config, args.domain, date=args.date)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"✅ Search output: {args.output} ({len(results)} results)", file=sys.stderr)


if __name__ == "__main__":
    main()
