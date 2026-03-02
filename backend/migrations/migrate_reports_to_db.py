"""Migrate existing report JSON files to SQLite database.

This script reads all report metadata from outputs/*.json files and inserts them
into the reports table. It preserves all fields and handles edge cases gracefully.
"""

import json
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import OUTPUT_DIR, DATA_DIR
from db import get_db, init_db


def migrate_reports():
    """Migrate all report JSON files to database."""
    # Ensure database and tables exist
    init_db()

    conn = get_db()
    cursor = conn.cursor()

    # Find all report JSON files (exclude _chunks.json and debug files)
    json_files = []
    for json_file in OUTPUT_DIR.glob("*.json"):
        if not json_file.stem.endswith("_chunks"):
            json_files.append(json_file)

    print(f"Found {len(json_files)} report JSON files to migrate")

    migrated = 0
    skipped = 0
    errors = []

    for json_file in sorted(json_files):
        report_id = json_file.stem

        try:
            # Load JSON metadata
            with open(json_file, "r", encoding="utf-8") as f:
                meta = json.load(f)

            # Check if already exists
            existing = cursor.execute(
                "SELECT report_id FROM reports WHERE report_id = ?",
                (report_id,)
            ).fetchone()

            if existing:
                print(f"  [SKIP] {report_id} (already exists in database)")
                skipped += 1
                continue

            # Prepare data for insertion
            # Convert complex fields to JSON strings
            locked_fields_json = json.dumps(meta.get("locked_fields", []))
            push_records_json = json.dumps(meta.get("push_records", {}))
            attachments_json = json.dumps(meta.get("attachments", []))

            # Store all other fields in metadata_json for extensibility
            metadata_json = json.dumps(meta, ensure_ascii=False)

            # Insert into database
            cursor.execute("""
                INSERT INTO reports (
                    report_id, bd_code, company_name, project_name,
                    industry, province, city, district,
                    is_listed, stock_code, website,
                    revenue, net_profit, revenue_yuan, net_profit_yuan,
                    valuation_yuan, valuation_date,
                    description, company_intro, industry_tags,
                    referral_status, is_traded, dept_primary, dept_owner,
                    annual_report_attachment, remarks,
                    score, rating, manual_rating, status, owner,
                    created_at, updated_at, file_size,
                    intro_attachment, metadata_json,
                    locked_fields, push_records, attachments
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?
                )
            """, (
                meta.get("report_id", report_id),
                meta.get("bd_code"),
                meta.get("company_name"),
                meta.get("project_name"),
                meta.get("industry"),
                meta.get("province"),
                meta.get("city"),
                meta.get("district"),
                meta.get("is_listed"),
                meta.get("stock_code"),
                meta.get("website"),
                meta.get("revenue"),
                meta.get("net_profit"),
                meta.get("revenue_yuan"),
                meta.get("net_profit_yuan"),
                meta.get("valuation_yuan"),
                meta.get("valuation_date"),
                meta.get("description"),
                meta.get("company_intro"),
                meta.get("industry_tags"),
                meta.get("referral_status"),
                meta.get("is_traded"),
                meta.get("dept_primary"),
                meta.get("dept_owner"),
                meta.get("annual_report_attachment"),
                meta.get("remarks"),
                meta.get("score"),
                meta.get("rating"),
                meta.get("manual_rating"),
                meta.get("status", "completed"),
                meta.get("owner"),
                meta.get("created_at"),
                meta.get("created_at"),  # updated_at = created_at initially
                meta.get("file_size"),
                meta.get("intro_attachment"),
                metadata_json,
                locked_fields_json,
                push_records_json,
                attachments_json,
            ))

            print(f"  [OK] Migrated {report_id}: {meta.get('company_name', 'N/A')}")
            migrated += 1

        except Exception as e:
            error_msg = f"  [ERROR] Error migrating {report_id}: {e}"
            print(error_msg)
            errors.append(error_msg)

    # Commit all changes
    conn.commit()
    conn.close()

    # Print summary
    print("\n" + "="*60)
    print("Migration Summary:")
    print(f"  Total files found: {len(json_files)}")
    print(f"  Successfully migrated: {migrated}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"  Errors: {len(errors)}")

    if errors:
        print("\nErrors:")
        for error in errors:
            print(error)

    print("="*60)

    return migrated, skipped, len(errors)


if __name__ == "__main__":
    print("Starting report metadata migration to database...")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Database path: {DATA_DIR / 'users.db'}")
    print()

    migrated, skipped, errors = migrate_reports()

    if errors > 0:
        sys.exit(1)
    else:
        print("\n[SUCCESS] Migration completed successfully!")
        sys.exit(0)
