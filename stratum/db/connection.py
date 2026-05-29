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
    return os.path.expanduser('~/WorkSpace/Stratum/DataBase')


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
    conn.commit()
