"""Attachment management utilities for v3.0."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from config import OUTPUT_DIR

log = logging.getLogger(__name__)


def copy_attachments_to_report(
    report_id: str,
    source_files: list[Path],
    related_filenames: list[str],
) -> list[dict]:
    """Copy related attachments to report's attachments directory.

    Args:
        report_id: Report ID
        source_files: List of source file paths (uploaded files)
        related_filenames: List of filenames that are related to this report

    Returns:
        List of attachment metadata:
        [
            {"filename": "file1.pdf", "size": 12345, "path": "reports/rpt_xxx/attachments/file1.pdf"},
            ...
        ]
    """
    attachments_dir = OUTPUT_DIR / f"{report_id}_attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    # Build filename → source_path mapping
    source_map = {}
    for src in source_files:
        source_map[src.name] = src

    attachments = []

    for filename in related_filenames:
        if filename not in source_map:
            log.warning(f"Related attachment {filename} not found in source files")
            continue

        src_path = source_map[filename]
        dst_path = attachments_dir / filename

        try:
            # Copy file
            shutil.copy2(src_path, dst_path)

            # Get file size
            size = dst_path.stat().st_size

            # Relative path for storage
            rel_path = str(dst_path)

            attachments.append({
                "filename": filename,
                "size": size,
                "path": rel_path,
            })

            log.info(f"Copied attachment {filename} to {rel_path}")

        except Exception as e:
            log.error(f"Failed to copy attachment {filename}: {e}")

    return attachments


def get_attachment_path(report_id: str, filename: str) -> Path:
    """Get the full path to an attachment file.

    Args:
        report_id: Report ID
        filename: Attachment filename

    Returns:
        Full path to the attachment file
    """
    return OUTPUT_DIR / f"{report_id}_attachments" / filename


def list_report_attachments(report_id: str) -> list[dict]:
    """List all attachments for a report.

    Args:
        report_id: Report ID

    Returns:
        List of attachment metadata (same format as copy_attachments_to_report)
    """
    attachments_dir = OUTPUT_DIR / f"{report_id}_attachments"

    if not attachments_dir.exists():
        return []

    attachments = []

    for file_path in attachments_dir.iterdir():
        if file_path.is_file():
            size = file_path.stat().st_size
            rel_path = str(file_path)

            attachments.append({
                "filename": file_path.name,
                "size": size,
                "path": rel_path,
            })

    return attachments


def serialize_attachments(attachments: list[dict]) -> str:
    """Serialize attachments list to JSON string for DB storage.

    Args:
        attachments: List of attachment metadata

    Returns:
        JSON string
    """
    return json.dumps(attachments, ensure_ascii=False)


def deserialize_attachments(attachments_json: str | None) -> list[dict]:
    """Deserialize attachments JSON string from DB.

    Args:
        attachments_json: JSON string from DB

    Returns:
        List of attachment metadata
    """
    if not attachments_json:
        return []

    try:
        return json.loads(attachments_json)
    except json.JSONDecodeError:
        log.error(f"Failed to deserialize attachments JSON: {attachments_json}")
        return []
