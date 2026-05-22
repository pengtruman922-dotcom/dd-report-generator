from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from config import OUTPUT_DIR

log = logging.getLogger(__name__)

_RESERVED_NAMES = {"manifest"}


def safe_parsed_text_filename(filename: str) -> str:
    """Return a safe markdown cache filename for a source attachment."""
    stem = Path(filename).stem.strip() or "attachment"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or "attachment"
    if stem.lower() in _RESERVED_NAMES:
        stem = f"{stem}_attachment"
    return f"{stem}.md"


def get_parsed_attachment_dir(report_id: str) -> Path:
    return OUTPUT_DIR / f"{report_id}_parsed_attachments"


def persist_parsed_attachment_texts(
    report_id: str,
    parsed_attachment_texts: dict[str, str] | None,
) -> dict[str, str]:
    """Persist parsed attachment text as md cache files and return original->path refs."""
    if not parsed_attachment_texts:
        return {}

    parsed_dir = get_parsed_attachment_dir(report_id)
    parsed_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = parsed_dir / "manifest.json"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except Exception as exc:
        log.warning("Failed to read parsed attachment manifest for %s: %s", report_id, exc)
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}

    refs: dict[str, str] = {}
    used_names = {
        str(item.get("parsed_filename", ""))
        for item in manifest.values()
        if isinstance(item, dict)
    }

    for original_name, text in (parsed_attachment_texts or {}).items():
        clean_text = (text or "").strip()
        original_name = Path(str(original_name)).name
        if not original_name or not clean_text:
            continue

        existing = manifest.get(original_name)
        if isinstance(existing, dict) and existing.get("parsed_filename"):
            parsed_name = str(existing["parsed_filename"])
        else:
            parsed_name = safe_parsed_text_filename(original_name)
            if parsed_name in used_names:
                stem = Path(parsed_name).stem
                suffix = 2
                while f"{stem}_{suffix}.md" in used_names:
                    suffix += 1
                parsed_name = f"{stem}_{suffix}.md"

        used_names.add(parsed_name)
        parsed_path = parsed_dir / parsed_name
        parsed_path.write_text(clean_text, encoding="utf-8")
        rel_path = str(parsed_path.relative_to(OUTPUT_DIR))
        manifest[original_name] = {
            "original_filename": original_name,
            "parsed_filename": parsed_name,
            "path": rel_path,
            "chars": len(clean_text),
        }
        refs[original_name] = str(parsed_path)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return refs


def load_parsed_attachment_text(report_id: str, filename: str) -> str | None:
    """Load cached parsed text for one attachment, if available."""
    parsed_dir = get_parsed_attachment_dir(report_id)
    manifest_path = parsed_dir / "manifest.json"
    filename = Path(str(filename)).name

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Failed to read parsed attachment manifest for %s: %s", report_id, exc)
            manifest = {}
        item = manifest.get(filename) if isinstance(manifest, dict) else None
        if isinstance(item, dict):
            candidates: list[Path] = []
            rel_path = item.get("path")
            parsed_filename = item.get("parsed_filename")
            if rel_path:
                candidates.append(OUTPUT_DIR / str(rel_path))
            if parsed_filename:
                candidates.append(parsed_dir / str(parsed_filename))
            for candidate in candidates:
                if candidate.exists() and candidate.is_file():
                    text = candidate.read_text(encoding="utf-8", errors="replace").strip()
                    if text:
                        return text

    for fallback_name in {safe_parsed_text_filename(filename), f"{Path(filename).stem}.md"}:
        fallback = parsed_dir / fallback_name
        if fallback.exists() and fallback.is_file():
            text = fallback.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
    return None
