"""Verify that the migration was successful.

This script compares the data in the database with the original JSON files
to ensure data integrity and completeness.
"""

import json
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import OUTPUT_DIR, DATA_DIR
from db import get_db


def verify_migration():
    """Verify migration by comparing database records with JSON files."""
    conn = get_db()
    cursor = conn.cursor()

    # Find all report JSON files
    json_files = []
    for json_file in OUTPUT_DIR.glob("*.json"):
        if not json_file.stem.endswith("_chunks"):
            json_files.append(json_file)

    print(f"Verifying {len(json_files)} reports...")
    print()

    verified = 0
    missing = []
    mismatches = []

    for json_file in sorted(json_files):
        report_id = json_file.stem

        try:
            # Load JSON metadata
            with open(json_file, "r", encoding="utf-8") as f:
                json_meta = json.load(f)

            # Fetch from database
            row = cursor.execute(
                "SELECT * FROM reports WHERE report_id = ?",
                (report_id,)
            ).fetchone()

            if not row:
                missing.append(report_id)
                print(f"  [MISSING] Missing in database: {report_id}")
                continue

            # Convert row to dict
            db_meta = dict(row)

            # Verify key fields
            key_fields = [
                "report_id", "bd_code", "company_name", "industry",
                "province", "score", "rating", "status", "owner"
            ]

            field_mismatches = []
            for field in key_fields:
                json_val = json_meta.get(field)
                db_val = db_meta.get(field)

                # Normalize None and empty string
                if json_val == "" or json_val is None:
                    json_val = None
                if db_val == "" or db_val is None:
                    db_val = None

                # Compare
                if json_val != db_val:
                    field_mismatches.append(
                        f"{field}: JSON={json_val!r} vs DB={db_val!r}"
                    )

            if field_mismatches:
                mismatches.append((report_id, field_mismatches))
                print(f"  [WARN] Mismatch in {report_id}:")
                for mismatch in field_mismatches:
                    print(f"      {mismatch}")
            else:
                print(f"  [OK] Verified {report_id}: {json_meta.get('company_name', 'N/A')}")
                verified += 1

        except Exception as e:
            print(f"  [ERROR] Error verifying {report_id}: {e}")
            mismatches.append((report_id, [str(e)]))

    conn.close()

    # Check for extra records in database
    conn = get_db()
    cursor = conn.cursor()
    db_report_ids = set(
        row["report_id"]
        for row in cursor.execute("SELECT report_id FROM reports").fetchall()
    )
    json_report_ids = set(f.stem for f in json_files)
    extra_in_db = db_report_ids - json_report_ids
    conn.close()

    # Print summary
    print("\n" + "="*60)
    print("Verification Summary:")
    print(f"  Total JSON files: {len(json_files)}")
    print(f"  Successfully verified: {verified}")
    print(f"  Missing in database: {len(missing)}")
    print(f"  Mismatches: {len(mismatches)}")
    print(f"  Extra in database: {len(extra_in_db)}")

    if missing:
        print("\nMissing reports:")
        for report_id in missing:
            print(f"  - {report_id}")

    if extra_in_db:
        print("\nExtra reports in database (not in JSON):")
        for report_id in extra_in_db:
            print(f"  - {report_id}")

    print("="*60)

    # Return success if all verified
    if len(missing) == 0 and len(mismatches) == 0:
        print("\n[SUCCESS] All reports verified successfully!")
        return True
    else:
        print("\n[WARNING] Verification found issues. Please review above.")
        return False


if __name__ == "__main__":
    print("Starting migration verification...")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Database path: {DATA_DIR / 'users.db'}")
    print()

    success = verify_migration()
    sys.exit(0 if success else 1)
