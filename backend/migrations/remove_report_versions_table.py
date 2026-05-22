"""Safely remove the deprecated report_versions table from SQLite.

This script creates a consistent SQLite backup first, then drops the
unused report_versions table if it still exists.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_DIR  # noqa: E402

DB_PATH = DATA_DIR / "users.db"


def get_migration_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _count_rows(conn: sqlite3.Connection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    return int(row[0]) if row else 0


def _make_backup_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DB_PATH.with_name(f"{DB_PATH.stem}.backup_before_drop_report_versions_{stamp}{DB_PATH.suffix}")


def _backup_database(src_conn: sqlite3.Connection, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    dst_conn = sqlite3.connect(str(backup_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()


def drop_report_versions_table(backup: bool = True) -> int:
    conn = get_migration_db()
    try:
        if not _table_exists(conn, "report_versions"):
            print("[INFO] report_versions table does not exist. Nothing to clean.")
            return 0

        row_count = _count_rows(conn, "report_versions")
        print(f"[INFO] Found deprecated table: report_versions ({row_count} rows)")

        backup_path: Path | None = None
        if backup:
            backup_path = _make_backup_path()
            _backup_database(conn, backup_path)
            print(f"[OK] Backup created: {backup_path}")

        conn.execute("DROP TABLE IF EXISTS report_versions")
        conn.commit()

        if _table_exists(conn, "report_versions"):
            print("[ERROR] Cleanup failed: report_versions still exists after DROP TABLE.")
            return 1

        print("[SUCCESS] Dropped deprecated report_versions table.")
        if backup_path is not None:
            print(f"[INFO] Rollback source: {backup_path}")
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove deprecated report_versions table from the DD report database.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the SQLite backup step before dropping the table.",
    )
    args = parser.parse_args()

    print("Starting deprecated table cleanup...")
    print(f"Database path: {DB_PATH}")
    print()
    return drop_report_versions_table(backup=not args.no_backup)


if __name__ == "__main__":
    raise SystemExit(main())
