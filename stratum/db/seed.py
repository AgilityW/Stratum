"""seed.py — Import domain.yaml and queries.yaml into SQLite.

Usage:
    python3 seed.py --domain storage
    python3 seed.py --domain storage --reset   # Drops all data first
"""

from __future__ import annotations

import argparse
import json
import os
import re
import yaml

from stratum.sourcing.discovery import normalize_include_domains
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _now() -> str:
    return datetime.now(CST).isoformat()


def seed(domain: str, reset: bool = False) -> None:
    from stratum.db.connection import get_db
    conn = get_db(domain)

    if reset:
        _reset_all(conn)

    project_root = _project_root()
    domain_path = os.path.join(project_root, 'domains', domain, 'domain.yaml')
    queries_path = os.path.join(project_root, 'domains', domain, 'queries.yaml')

    # Load domain config
    with open(domain_path) as f:
        domain_cfg = yaml.safe_load(f)

    # Seed sources from legacy channels and current source_registry.
    _seed_sources(conn, domain_cfg)

    # Seed entities from companies
    _seed_entities(conn, domain_cfg.get('companies', []))

    # Seed terms from domain.yaml terms section
    _seed_terms(conn, domain_cfg.get('terms', []))

    # Seed keywords from entities + terms
    _seed_keywords(conn, domain_cfg)

    # Seed queries from queries.yaml
    if os.path.exists(queries_path):
        with open(queries_path) as f:
            queries_cfg = yaml.safe_load(f)
        _seed_queries(conn, queries_cfg)

    db_path = os.path.join(_resolve_workspace(), domain, f'{domain}.db')
    _print_stats(conn)
    conn.commit()
    conn.close()
    print(f'✅ Seed complete: {db_path}')


def _reset_all(conn):
    tables = [
        'keyword_event', 'keyword_article', 'keywords',
        'thread_entities', 'cascade_logs', 'coverage', 'entity_snapshots',
        'judgments', 'causal_edges', 'events',
        'threads', 'terms', 'entities',
        'queries', 'source_profiles', 'sources',
        'articles',
    ]
    for t in tables:
        try:
            conn.execute(f'DELETE FROM {t}')
        except Exception:
            pass
    conn.commit()
    print('🗑️  All tables cleared.')


def _seed_sources(conn, domain_cfg: dict):
    count = 0
    for ch in _iter_source_configs(domain_cfg):
        ch_id = ch.get('id', '')
        if not ch_id:
            continue
        urls = ch.get('urls') or []
        url = ch.get('url') or (urls[0] if urls else '')
        domain = _extract_domain(url)
        conn.execute('''
            INSERT OR REPLACE INTO sources (id, name, domain, type, url, locale, reliability, status, first_seen, added_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ch_id,
            ch.get('name', ch_id),
            domain,
            ch.get('type', ch.get('category', 'media')).upper(),
            url,
            ch.get('locale', 'en'),
            ch.get('reliability', 0.8),
            ch.get('status', 'active'),
            _now(),
            ch.get('added_by', 'seed'),
        ))
        count += 1
    print(f'  Sources: {count} seeded')


def _iter_source_configs(domain_cfg: dict) -> list[dict]:
    """Return normalized source configs from channels and source_registry."""
    seen: set[str] = set()
    sources: list[dict] = []

    for ch in domain_cfg.get('channels', []):
        sid = ch.get('id')
        if sid and sid not in seen:
            seen.add(sid)
            sources.append({**ch, 'added_by': ch.get('added_by', 'seed')})

    for src in domain_cfg.get('source_registry', {}).get('sources', []):
        sid = src.get('id')
        if sid and sid not in seen:
            seen.add(sid)
            sources.append({**src, 'added_by': src.get('added_by', 'source_registry')})

    return sources


def _seed_entities(conn, companies: list):
    count = 0
    for co in companies:
        co_id = co.get('id', '')
        if not co_id:
            continue
        aliases = co.get('aliases', {})
        all_aliases = []
        for locale, name in aliases.items():
            if name not in all_aliases:
                all_aliases.append(name)
        conn.execute('''
            INSERT OR REPLACE INTO entities (id, type, name_en, name_zh, aliases, status, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            co_id,
            co.get('type', 'COMPANY'),
            aliases.get('en', ''),
            aliases.get('zh-CN', ''),
            json.dumps(all_aliases, ensure_ascii=False),
            'active',
            _now(),
        ))
        count += 1
    print(f'  Entities: {count} seeded')


def _seed_terms(conn, terms: list):
    count = 0
    for t in terms:
        t_id = t.get('id', '')
        if not t_id:
            continue
        aliases = t.get('aliases', {})
        conn.execute('''
            INSERT OR REPLACE INTO terms (id, type, name_en, name_zh, aliases, parent_id, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            t_id,
            t.get('type', 'TECHNOLOGY'),
            aliases.get('en', ''),
            aliases.get('zh-CN', ''),
            json.dumps(list(aliases.values()), ensure_ascii=False),
            None,  # parent term resolution later
            _now(),
        ))
        count += 1

    # Second pass: resolve parent terms
    for t in terms:
        children = t.get('children', [])
        for child_id in children:
            conn.execute('UPDATE terms SET parent_id = ? WHERE id = ?', (t.get('id'), child_id))

    print(f'  Terms: {count} seeded')


def _seed_keywords(conn, domain_cfg: dict):
    count = 0

    # From companies
    for co in domain_cfg.get('companies', []):
        co_id = co.get('id', '')
        if not co_id:
            continue
        aliases = co.get('aliases', {})
        for locale, name in aliases.items():
            if locale.startswith('zh'):
                kw_id = f'kw-{co_id}-zh'
            elif locale == 'en':
                kw_id = f'kw-{co_id}-en'
            else:
                kw_id = f'kw-{co_id}-{locale}'
            conn.execute('''
                INSERT OR REPLACE INTO keywords (id, text, locale, type, entity_id, is_core, first_seen, source)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ''', (kw_id, name, locale, 'COMPANY', co_id, _now(), 'domain.yaml'))
            count += 1

    # From terms
    for t in domain_cfg.get('terms', []):
        t_id = t.get('id', '')
        if not t_id:
            continue
        aliases = t.get('aliases', {})
        for locale, name in aliases.items():
            kw_id = f'kw-{t_id}-{locale[:2]}'
            conn.execute('''
                INSERT OR REPLACE INTO keywords (id, text, locale, type, term_id, is_core, first_seen, source)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ''', (kw_id, name, locale, 'TECHNOLOGY', t_id, _now(), 'domain.yaml'))
            count += 1

    print(f'  Keywords: {count} seeded')


def _seed_queries(conn, queries_cfg: dict):
    count = 0
    now = _now()
    has_dimension = _has_column(conn, "queries", "dimension")
    has_include_domains = _has_column(conn, "queries", "include_domains")

    queries = queries_cfg.get('queries', {})
    if not queries:
        raise ValueError("queries.yaml must define structured queries")

    # Queries are grouped by intent. Supports both intent -> locale -> list and
    # intent -> dimension -> locale -> list.
    for intent, intent_map in queries.items():
        for key, value in intent_map.items():
            dimension = "general"
            locale_groups = value.items() if isinstance(value, dict) else [(key, value)]
            if isinstance(value, dict):
                dimension = str(key)
            for locale, qlist in locale_groups:
                for q in qlist or []:
                    text = q.get('text', q.get('query', '')) if isinstance(q, dict) else q
                    qid = q.get('id', '') if isinstance(q, dict) else ''
                    thread_id = q.get('thread', q.get('thread_id')) if isinstance(q, dict) else None
                    item_dimension = q.get('dimension', dimension) if isinstance(q, dict) else dimension
                    include_domains = _normalize_include_domains(
                        q.get('include_domains', q.get('domains')) if isinstance(q, dict) else []
                    )
                    if not qid:
                        qid = f'q-{intent}-{count:03d}'
                    columns = ["id", "text", "locale", "intent"]
                    values = [qid, text, locale, intent]
                    if has_dimension:
                        columns.append("dimension")
                        values.append(item_dimension)
                    if has_include_domains:
                        columns.append("include_domains")
                        values.append(json.dumps(include_domains, ensure_ascii=False))
                    columns.extend(["thread_id", "status", "created_at"])
                    values.extend([thread_id, "active", now])
                    placeholders = ", ".join(["?"] * len(values))
                    conn.execute(f'''
                        INSERT OR REPLACE INTO queries ({", ".join(columns)})
                        VALUES ({placeholders})
                    ''', values)
                    count += 1

    print(f'  Queries: {count} seeded')


def _has_column(conn, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _normalize_include_domains(domains) -> list[str]:
    return normalize_include_domains(domains)


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    if not url:
        return ''
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return ''


def _resolve_workspace() -> str:
    current = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current))
    config_path = os.path.join(project_root, 'config.yaml')
    if os.path.exists(config_path):
        with open(config_path) as f:
            raw = f.read()
        for match in re.finditer(r'\$\{(HOME)\}', raw, re.IGNORECASE):
            raw = raw.replace(match.group(0), os.path.expanduser('~'))
        cfg = yaml.safe_load(raw)
        db_dir = cfg.get('db_dir', '')
        if db_dir:
            return os.path.expandvars(os.path.expanduser(db_dir))
    return os.path.expanduser('~/stratum/db')


def _print_stats(conn):
    tables = ['sources', 'queries', 'keywords', 'entities', 'terms', 'threads', 'events',
              'causal_edges', 'judgments']
    for t in tables:
        row = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()
        if row and row[0] > 0:
            print(f'  {t}: {row[0]}')


def main():
    parser = argparse.ArgumentParser(description='Seed Stratum database from YAML configs')
    parser.add_argument('--domain', '-d', required=True, help='Domain ID (e.g. storage)')
    parser.add_argument('--reset', action='store_true', help='Clear all data before seeding')
    args = parser.parse_args()

    # Ensure domain exists
    domain_path = os.path.join(_project_root(), 'domains', args.domain, 'domain.yaml')
    if not os.path.exists(domain_path):
        print(f'❌ Domain "{args.domain}" not found: {domain_path}')
        sys.exit(1)

    seed(args.domain, reset=args.reset)


if __name__ == '__main__':
    main()
