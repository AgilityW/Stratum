"""Database migration support utilities.

This module prepares production-safe migration workflows without changing the
runtime database path automatically. Callers must opt in to creating the
migration ledger, recording migrations, or taking backups.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MIGRATION_TABLE = "schema_migrations"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


@dataclass(frozen=True)
class DatabaseState:
    """Inspectable migration state for one SQLite database."""

    path: str
    user_version: int
    has_migration_table: bool
    applied_migrations: list[dict[str, Any]]
    tables: list[str]


def inspect_database(db_path: str | os.PathLike[str]) -> DatabaseState:
    """Inspect a SQLite database without mutating it."""
    path = str(Path(db_path).expanduser())
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        has_table = MIGRATION_TABLE in tables
        migrations: list[dict[str, Any]] = []
        if has_table:
            migrations = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT version, description, checksum, applied_at
                      FROM {MIGRATION_TABLE}
                     ORDER BY version
                    """
                ).fetchall()
            ]
        return DatabaseState(
            path=path,
            user_version=user_version,
            has_migration_table=has_table,
            applied_migrations=migrations,
            tables=tables,
        )
    finally:
        conn.close()


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    """Create the migration ledger table if a migration run opts into it."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            checksum TEXT,
            applied_at TEXT NOT NULL
        )
        """
    )


def record_migration(
    conn: sqlite3.Connection,
    version: str,
    description: str,
    checksum: str | None = None,
) -> None:
    """Record an applied migration in the ledger."""
    ensure_migration_table(conn)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO {MIGRATION_TABLE}
            (version, description, checksum, applied_at)
        VALUES (?, ?, ?, ?)
        """,
        (version, description, checksum, datetime.now(timezone.utc).isoformat()),
    )


def migration_applied(conn: sqlite3.Connection, version: str) -> bool:
    """Return whether a migration version is already recorded."""
    ensure_migration_table(conn)
    row = conn.execute(
        f"SELECT 1 FROM {MIGRATION_TABLE} WHERE version = ?",
        (version,),
    ).fetchone()
    return bool(row)


def apply_migration_file(
    conn: sqlite3.Connection,
    migration_path: str | os.PathLike[str],
    version: str,
    description: str,
) -> bool:
    """Apply one SQL migration file and record it.

    Returns True when applied and False when the version already exists in the
    ledger. The caller owns backup/rehearsal policy before invoking this.
    """
    path = Path(migration_path).expanduser()
    if migration_applied(conn, version):
        return False

    sql = path.read_text()
    checksum = file_sha256(path)
    try:
        conn.executescript(sql)
        record_migration(conn, version, description, checksum=checksum)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def apply_foundation_migration(conn: sqlite3.Connection) -> bool:
    """Apply the explicit DB foundation 0.1 schema migration."""
    return apply_migration_file(
        conn,
        MIGRATIONS_DIR / "000010_foundation.sql",
        "0.1.0",
        "database foundation 0.1 tables for reports, evidence, and lineage",
    )


def apply_report_item_policy_decision_migration(conn: sqlite3.Connection) -> bool:
    """Add structured synthesis-policy metadata to report items."""
    if migration_applied(conn, "0.1.1"):
        return False
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(report_items)").fetchall()
    }
    if "policy_decision" in columns:
        record_migration(
            conn,
            "0.1.1",
            "report item synthesis policy decision metadata",
            checksum=file_sha256(MIGRATIONS_DIR / "000011_policy.sql"),
        )
        conn.commit()
        return False
    return apply_migration_file(
        conn,
        MIGRATIONS_DIR / "000011_policy.sql",
        "0.1.1",
        "report item synthesis policy decision metadata",
    )


def backup_database(
    db_path: str | os.PathLike[str],
    backup_dir: str | os.PathLike[str],
    label: str,
) -> str:
    """Create a consistent SQLite backup and copy WAL sidecars if present.

    Returns the main backup DB path. The backup filename includes a timestamp and
    the provided label so migration runs can be traced to a deployment step.
    """
    source = Path(db_path).expanduser()
    if not source.exists():
        raise FileNotFoundError(str(source))

    target_dir = Path(backup_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in label).strip("-")
    target = target_dir / f"{source.stem}.{safe_label}.{timestamp}{source.suffix}"

    src_conn = sqlite3.connect(str(source))
    try:
        dst_conn = sqlite3.connect(str(target))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, Path(f"{target}{suffix}"))

    return str(target)


def file_sha256(path: str | os.PathLike[str]) -> str:
    """Return a SHA256 checksum for migration files or backup artifacts."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
