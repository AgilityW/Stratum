"""Tests for explicit database management commands."""

from __future__ import annotations

import json
import sqlite3


def test_db_manage_inspect_is_read_only(tmp_path, capsys):
    from stratum.db.manage import main

    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    assert main(["inspect", "--db", str(db_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["path"] == str(db_path)
    assert payload["has_migration_table"] is False
    assert payload["tables"] == ["t"]


def test_db_manage_apply_foundation_requires_backup_unless_test_optout(tmp_path, capsys):
    from stratum.db.manage import main

    db_dir = tmp_path / "db"

    rc = main(["apply-foundation", "--domain", "storage", "--db-dir", str(db_dir)])
    assert rc == 2
    capsys.readouterr()

    assert main([
        "apply-foundation",
        "--domain",
        "storage",
        "--db-dir",
        str(db_dir),
        "--no-backup",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert (db_dir / "storage" / "storage.db").exists()


def test_db_manage_build_cascade_fixture_outputs_analysis(tmp_path, capsys):
    from stratum.db.manage import main

    assert main([
        "build-cascade-fixture",
        "--domain",
        "storage",
        "--db-dir",
        str(tmp_path / "db"),
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["daily_trend"]["top_terms"][0] == {"id": "hbm", "count": 3}
    assert payload["judgment_status"]["counts"] == {"supported": 1, "pending": 1}
    consumed_reports = {
        entry["source_report_id"]
        for entry in payload["yearly_lineage"]["lineage"]
        if entry.get("relation") == "consumes" and entry.get("source_report_id")
    }
    assert "report-storage-quarterly-2026-Q2" in consumed_reports
    assert len(consumed_reports) == 7
