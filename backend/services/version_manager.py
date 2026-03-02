"""Version management for reports - create, list, restore versions."""

import json
import logging
import uuid
from pathlib import Path

from config import OUTPUT_DIR
from db import get_db

log = logging.getLogger(__name__)


def create_version(report_id: str, reason: str = "auto_backup", created_by: str | None = None) -> str:
    """Create a version snapshot of a report before modification.

    Returns version_id.
    """
    from routers.report import _get_report_paths, _load_report_meta

    paths = _get_report_paths(report_id)
    md_path = paths["md"]

    if not md_path.exists():
        raise FileNotFoundError(f"Report {report_id} not found")

    # Read current content
    content = md_path.read_text(encoding="utf-8")

    # Load metadata
    meta = _load_report_meta(report_id)
    metadata_json = json.dumps(meta, ensure_ascii=False) if meta else None

    # Get next version number
    conn = get_db()
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT MAX(version_number) FROM report_versions WHERE report_id = ?",
            (report_id,)
        ).fetchone()
        version_number = (row[0] or 0) + 1

        # Create version record
        version_id = uuid.uuid4().hex[:12]
        cursor.execute(
            """INSERT INTO report_versions
               (version_id, report_id, version_number, content, metadata_json, created_by, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (version_id, report_id, version_number, content, metadata_json, created_by, reason)
        )
        conn.commit()

        log.info(f"Created version {version_number} for report {report_id}: {reason}")
        return version_id
    finally:
        conn.close()


def list_versions(report_id: str) -> list[dict]:
    """List all versions for a report, newest first."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        rows = cursor.execute(
            """SELECT version_id, version_number, created_at, created_by, reason,
                      length(content) as content_size
               FROM report_versions
               WHERE report_id = ?
               ORDER BY version_number DESC""",
            (report_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
