"""connection.py — SQLite database connection manager.

Usage:
    from stratum.db.connection import get_db
    conn = get_db('storage')           # → sqlite3.Connection
    conn.close()
"""

from __future__ import annotations

import sqlite3
import os
import yaml


def _resolve_workspace() -> str:
    """Resolve workspace path from config.yaml."""
    env_db_dir = os.environ.get('STRATUM_DB_DIR')
    if env_db_dir:
        return os.path.expandvars(os.path.expanduser(env_db_dir))

    # Find project root
    current = os.path.dirname(os.path.abspath(__file__))
    # stratum/db/ → stratum/ → project root
    project_root = os.path.dirname(os.path.dirname(current))
    config_path = os.path.join(project_root, 'config.yaml')

    if os.path.exists(config_path):
        import re
        with open(config_path) as f:
            raw = f.read()
        # Resolve ${HOME} etc
        for match in re.finditer(r'\$\{(HOME)\}', raw, re.IGNORECASE):
            raw = raw.replace(match.group(0), os.path.expanduser('~'))
        cfg = yaml.safe_load(raw)
        db_dir = cfg.get('db_dir', '')
        if db_dir:
            return os.path.expandvars(os.path.expanduser(db_dir))

    # Fallback
    return os.path.expanduser('~/stratum/db')


def get_db_path(domain: str) -> str:
    """Get database file path for a domain."""
    workspace = _resolve_workspace()
    return os.path.join(workspace, domain, f'{domain}.db')


def get_db(domain: str) -> sqlite3.Connection:
    """Get a database connection for a domain. Creates DB + tables if needed."""
    db_path = get_db_path(domain)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Run schema if tables don't exist
    _ensure_schema(conn)

    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path) as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    _ensure_migrations(conn)
    conn.commit()


def _ensure_migrations(conn: sqlite3.Connection) -> None:
    """Apply lightweight additive migrations for existing domain DBs."""
    query_columns = {row["name"] for row in conn.execute("PRAGMA table_info(queries)").fetchall()}
    if "dimension" not in query_columns:
        conn.execute("ALTER TABLE queries ADD COLUMN dimension TEXT DEFAULT 'general'")
    if "include_domains" not in query_columns:
        conn.execute("ALTER TABLE queries ADD COLUMN include_domains TEXT")

    event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "status" not in event_columns:
        conn.execute("ALTER TABLE events ADD COLUMN status TEXT DEFAULT 'emerging'")
    if "priority" not in event_columns:
        conn.execute("ALTER TABLE events ADD COLUMN priority INTEGER DEFAULT 3")
