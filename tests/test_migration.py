"""Tests for production-safe database migration utilities."""

from __future__ import annotations

import sqlite3


def test_inspect_database_is_read_only(tmp_path):
    from stratum.db.migration import inspect_database

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE events (id TEXT PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    state = inspect_database(db_path)

    assert state.path == str(db_path)
    assert state.user_version == 4
    assert state.has_migration_table is False
    assert state.applied_migrations == []
    assert state.tables == ["events"]


def test_record_migration_creates_ledger(tmp_path):
    from stratum.db.migration import inspect_database, record_migration

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    record_migration(conn, "0.1.1", "add report tables", checksum="abc123")
    conn.commit()
    conn.close()

    state = inspect_database(db_path)

    assert state.has_migration_table is True
    assert state.applied_migrations == [
        {
            "version": "0.1.1",
            "description": "add report tables",
            "checksum": "abc123",
            "applied_at": state.applied_migrations[0]["applied_at"],
        }
    ]


def test_backup_database_creates_consistent_copy(tmp_path):
    from stratum.db.migration import backup_database, file_sha256

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE events (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO events VALUES ('ev-1', 'HBM update')")
    conn.commit()
    conn.close()

    backup_path = backup_database(db_path, tmp_path / "backups", "pre-0-1-deploy")

    backup_conn = sqlite3.connect(backup_path)
    row = backup_conn.execute("SELECT id, title FROM events").fetchone()
    backup_conn.close()

    assert row == ("ev-1", "HBM update")
    assert file_sha256(backup_path)


def test_apply_foundation_migration_is_explicit_and_idempotent(tmp_path):
    from stratum.db.connection import _ensure_schema
    from stratum.db.migration import apply_foundation_migration, inspect_database

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)

    assert apply_foundation_migration(conn) is True
    assert apply_foundation_migration(conn) is False
    conn.close()

    state = inspect_database(db_path)

    assert state.has_migration_table is True
    assert state.applied_migrations[0]["version"] == "0.1.0"
    assert "reports" in state.tables
    assert "report_items" in state.tables
    assert "report_item_articles" in state.tables
    assert "event_articles" in state.tables


def test_report_item_policy_decision_migration_adds_column_to_existing_foundation(tmp_path):
    from stratum.db.migration import apply_report_item_policy_decision_migration, inspect_database

    db_path = tmp_path / "storage.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE report_items (
            id TEXT PRIMARY KEY,
            report_id TEXT NOT NULL,
            section_id TEXT,
            section_key TEXT,
            position INTEGER,
            title TEXT,
            body TEXT,
            signal_type TEXT,
            importance INTEGER,
            confidence TEXT
        )
    """)

    assert apply_report_item_policy_decision_migration(conn) is True
    assert apply_report_item_policy_decision_migration(conn) is False
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(report_items)").fetchall()}
    conn.close()
    state = inspect_database(db_path)

    assert "policy_decision" in columns
    assert state.applied_migrations[-1]["version"] == "0.1.1"
