#!/usr/bin/env python3
"""search.py — Deterministic search stage: calls search engines directly via API.

Replaces the LLM-driven Agent Search placeholder.
Reads engine configs from config.yaml, queries from domains/{domain}/queries.yaml.
Calls each engine's API with freshness filters, maps response fields to
Stratum raw.json schema, and deduplicates by URL.

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
    """Load and resolve env vars in config.yaml."""
    with open(config_path) as f:
        raw = f.read()
    # Resolve ${VAR} references
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


def call_bocha(query: str, count: int, api_key: str) -> list[dict]:
    """Call Bocha AI search API. Returns normalized results."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "https://api.bocha.cn/v1/web-search",
             "-H", f"Authorization: Bearer {api_key}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({
                 "query": query,
                 "count": count,
                 "freshness": "oneDay",
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


def call_tavily(query: str, count: int, api_key: str) -> list[dict]:
    """Call Tavily search API. Returns normalized results."""
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
                 "time_range": "day",
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


def _normalize_date(date_str: str) -> str:
    """Normalize date to YYYY-MM-DD. Strips time and TZ."""
    if not date_str:
        return ""
    date_str = date_str.strip()
    # ISO with time: 2026-05-29T00:00:00+08:00 → 2026-05-29
    m = re.match(r'(\d{4}-\d{2}-\d{2})', date_str)
    return m.group(1) if m else ""


def run_search(config: dict, queries_config: dict, domain_id: str) -> list[dict]:
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
                results = call_bocha(query, count, bocha_key)
            elif engine == "tavily" and tavily_key:
                results = call_tavily(query, count, tavily_key)
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
    parser.add_argument("--queries", required=True, help="Path to queries.yaml")
    parser.add_argument("--output", "-o", required=True, help="Output raw.json path")
    args = parser.parse_args()

    config = load_config(args.config)
    queries_config = load_queries(args.queries, args.date)

    results = run_search(config, queries_config, args.domain)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"✅ Search output: {args.output} ({len(results)} results)", file=sys.stderr)


if __name__ == "__main__":
    main()
