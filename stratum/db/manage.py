"""Command-line database management helpers.

These commands are explicit operational tools. They do not run from normal
pipeline startup and therefore preserve the current baseline runtime path.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

from stratum.db.cascade_fixture import analyze_constructed_cascade, build_constructed_cascade
from stratum.db.connection import get_db, get_db_path
from stratum.db.migration import apply_foundation_migration, backup_database, inspect_database
from stratum.db.synthesis import synthesize_cascade_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stratum database management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a SQLite DB without mutation")
    inspect_parser.add_argument("--db", required=True, help="SQLite DB path")

    backup_parser = subparsers.add_parser("backup", help="Create a consistent SQLite backup")
    backup_parser.add_argument("--db", required=True, help="SQLite DB path")
    backup_parser.add_argument("--backup-dir", required=True, help="Backup output directory")
    backup_parser.add_argument("--label", default="manual", help="Backup label")

    migrate_parser = subparsers.add_parser("apply-foundation", help="Apply the explicit DB foundation 0.1 migration")
    migrate_parser.add_argument("--domain", required=True, help="Domain id")
    migrate_parser.add_argument("--db-dir", help="Override STRATUM_DB_DIR")
    migrate_parser.add_argument("--backup-dir", help="Backup output directory before migration")
    migrate_parser.add_argument("--no-backup", action="store_true", help="Allow migration without backup for disposable test DBs")

    build_parser = subparsers.add_parser("build-cascade-fixture", help="Build and analyze the constructed cascade fixture")
    build_parser.add_argument("--domain", default="storage", help="Domain id")
    build_parser.add_argument("--db-dir", required=True, help="Target test DB root")

    analyze_parser = subparsers.add_parser("analyze-cascade-fixture", help="Analyze an existing constructed cascade fixture")
    analyze_parser.add_argument("--domain", default="storage", help="Domain id")
    analyze_parser.add_argument("--db-dir", required=True, help="Target test DB root")

    synthesis_parser = subparsers.add_parser("synthesize-report", help="Build one higher-scale report from DB cascade inputs")
    synthesis_parser.add_argument("--domain", required=True, help="Domain id")
    synthesis_parser.add_argument("--scale", required=True, choices=["weekly", "monthly", "quarterly", "yearly"])
    synthesis_parser.add_argument("--period", help="Target period id. Optional when --start-date/--end-date are provided.")
    synthesis_parser.add_argument("--start-date", help="Custom window start date YYYY-MM-DD")
    synthesis_parser.add_argument("--end-date", help="Custom window end date YYYY-MM-DD")
    synthesis_parser.add_argument("--db-dir", help="Override STRATUM_DB_DIR")
    synthesis_parser.add_argument("--max-threads", type=int, default=6, help="Maximum thread trend items")

    args = parser.parse_args(argv)
    if args.command == "inspect":
        _write_json(dataclasses.asdict(inspect_database(args.db)))
        return 0
    if args.command == "backup":
        path = backup_database(args.db, args.backup_dir, args.label)
        _write_json({"backup_path": path})
        return 0
    if args.command == "apply-foundation":
        return _apply_foundation_command(args)
    if args.command == "build-cascade-fixture":
        os.environ["STRATUM_DB_DIR"] = os.path.expandvars(os.path.expanduser(args.db_dir))
        _write_json(build_constructed_cascade(args.domain))
        return 0
    if args.command == "analyze-cascade-fixture":
        os.environ["STRATUM_DB_DIR"] = os.path.expandvars(os.path.expanduser(args.db_dir))
        _write_json(analyze_constructed_cascade(args.domain))
        return 0
    if args.command == "synthesize-report":
        if args.db_dir:
            os.environ["STRATUM_DB_DIR"] = os.path.expandvars(os.path.expanduser(args.db_dir))
        _write_json(synthesize_cascade_report(
            args.domain,
            args.scale,
            args.period,
            window_start=args.start_date,
            window_end=args.end_date,
            max_threads=args.max_threads,
        ))
        return 0
    parser.error(f"unsupported command: {args.command}")
    return 2


def _apply_foundation_command(args: argparse.Namespace) -> int:
    if args.db_dir:
        os.environ["STRATUM_DB_DIR"] = os.path.expandvars(os.path.expanduser(args.db_dir))
    db_path = get_db_path(args.domain)
    if not args.backup_dir and not args.no_backup:
        print(
            "apply-foundation requires --backup-dir, or --no-backup for disposable test DBs",
            file=sys.stderr,
        )
        return 2

    backup_path = None
    if args.backup_dir and os.path.exists(db_path):
        backup_path = backup_database(db_path, args.backup_dir, f"foundation-{args.domain}")

    conn = get_db(args.domain)
    try:
        applied = apply_foundation_migration(conn)
    finally:
        conn.close()
    _write_json({"db_path": db_path, "backup_path": backup_path, "applied": applied})
    return 0


def _write_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
