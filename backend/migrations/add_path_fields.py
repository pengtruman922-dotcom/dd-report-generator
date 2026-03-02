"""Add file path fields to reports table for unified storage model.

This migration adds md_path, chunks_path, debug_dir, and attachments_dir fields
to the reports table to enable database-managed file paths.
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import OUTPUT_DIR, DATA_DIR
from db import get_db


def add_path_fields():
    """Add path fields to reports table."""
    conn = get_db()
    cursor = conn.cursor()

    print("Adding path fields to reports table...")

    # Check if columns already exist
    columns = cursor.execute("PRAGMA table_info(reports)").fetchall()
    existing_cols = {col[1] for col in columns}

    fields_to_add = []
    if "md_path" not in existing_cols:
        fields_to_add.append("md_path TEXT")
    if "chunks_path" not in existing_cols:
        fields_to_add.append("chunks_path TEXT")
    if "debug_dir" not in existing_cols:
        fields_to_add.append("debug_dir TEXT")
    if "attachments_dir" not in existing_cols:
        fields_to_add.append("attachments_dir TEXT")

    if not fields_to_add:
        print("  [INFO] Path fields already exist, skipping...")
        conn.close()
        return

    # Add columns
    for field in fields_to_add:
        try:
            cursor.execute(f"ALTER TABLE reports ADD COLUMN {field}")
            print(f"  [OK] Added column: {field.split()[0]}")
        except Exception as e:
            print(f"  [ERROR] Failed to add {field}: {e}")

    conn.commit()

    # Backfill paths for existing reports
    print("\nBackfilling paths for existing reports...")
    rows = cursor.execute("SELECT report_id FROM reports").fetchall()

    for row in rows:
        report_id = row[0]
        md_path = str(OUTPUT_DIR / f"{report_id}.md")
        chunks_path = str(OUTPUT_DIR / f"{report_id}_chunks.json")
        debug_dir = str(OUTPUT_DIR / f"{report_id}_debug")
        attachments_dir = str(OUTPUT_DIR / f"{report_id}_attachments")

        cursor.execute("""
            UPDATE reports SET
                md_path = ?,
                chunks_path = ?,
                debug_dir = ?,
                attachments_dir = ?
            WHERE report_id = ?
        """, (md_path, chunks_path, debug_dir, attachments_dir, report_id))

        print(f"  [OK] Backfilled paths for {report_id}")

    conn.commit()
    conn.close()

    print("\n[SUCCESS] Path fields added and backfilled successfully!")


if __name__ == "__main__":
    print("Starting path fields migration...")
    print(f"Database path: {DATA_DIR / 'users.db'}")
    print()

    add_path_fields()
    sys.exit(0)
