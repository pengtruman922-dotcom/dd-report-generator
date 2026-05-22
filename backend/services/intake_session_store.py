"""Shared intake session storage and in-memory attachment parsing helpers.

This module keeps the small subset of legacy upload/session helpers that the
Current intake flow still depends on, without exposing the old upload router.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

from fastapi import HTTPException

from config import UPLOAD_DIR
from db import get_db

log = logging.getLogger(__name__)

_sessions_cache: dict[str, dict] = {}


def _save_session(session_id: str, data: dict) -> None:
    """Persist session data to SQLite, spilling parsed texts to disk."""
    parsed_texts = data.get("parsed_texts", {})
    if parsed_texts:
        texts_dir = UPLOAD_DIR / session_id / "_parsed"
        texts_dir.mkdir(parents=True, exist_ok=True)
        refs: dict[str, list[dict]] = {}
        for bd_code, items in parsed_texts.items():
            refs[bd_code] = []
            for i, (filename, text) in enumerate(items):
                text_file = texts_dir / f"{bd_code}_{i}.txt"
                text_file.write_text(text, encoding="utf-8")
                refs[bd_code].append({"filename": filename, "path": str(text_file)})
        data_to_store = {**data, "parsed_texts_refs": refs}
    else:
        data_to_store = {**data}

    data_to_store.pop("parsed_texts", None)
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO upload_sessions (session_id, data) VALUES (?, ?)",
            (session_id, json.dumps(data_to_store, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _load_session(session_id: str) -> dict | None:
    """Load session data from SQLite and restore parsed text refs."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT data FROM upload_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    data = json.loads(row["data"])
    refs = data.pop("parsed_texts_refs", {})
    parsed_texts: dict[str, list[tuple[str, str]]] = {}
    for bd_code, items in refs.items():
        parsed_texts[bd_code] = []
        for item in items:
            text_path = Path(item["path"])
            if text_path.exists():
                text = text_path.read_text(encoding="utf-8")
                parsed_texts[bd_code].append((item["filename"], text))
    data["parsed_texts"] = parsed_texts
    return data


def get_session(session_id: str) -> dict:
    """Get session from cache or persisted storage."""
    if session_id in _sessions_cache:
        return _sessions_cache[session_id]

    data = _load_session(session_id)
    if data is None:
        raise HTTPException(404, f"Session {session_id} not found")

    _sessions_cache[session_id] = data
    return data


def persist_session(session_id: str, data: dict) -> None:
    """Save to both cache and SQLite."""
    _sessions_cache[session_id] = data
    _save_session(session_id, data)


def get_sessions() -> dict[str, dict]:
    return _sessions_cache


def parse_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Parse attachment text from raw in-memory bytes."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return _parse_pdf_from_bytes(filename, raw_bytes)
    if ext in (".md", ".txt"):
        return raw_bytes.decode("utf-8", errors="replace")
    if ext == ".docx":
        return _parse_docx_from_bytes(filename, raw_bytes)
    if ext == ".pptx":
        return _parse_pptx_from_bytes(filename, raw_bytes)
    return ""


def _parse_pdf_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Parse PDF from in-memory bytes using text extraction with OCR fallback."""
    if not raw_bytes.startswith(b"%PDF"):
        log.warning("PDF header invalid for %s; file may be encrypted/protected", filename)
        return ""

    from parsers.pdf_parser import extract_pdf_text_from_bytes

    return extract_pdf_text_from_bytes(filename, raw_bytes)


def _parse_docx_from_bytes(filename: str, raw_bytes: bytes) -> str:
    try:
        from parsers.docx_parser import extract_docx_text

        return extract_docx_text(io.BytesIO(raw_bytes))
    except Exception as e:
        log.debug("  DOCX bytes parse failed for %s: %s", filename, e)
        return ""


def _parse_pptx_from_bytes(filename: str, raw_bytes: bytes) -> str:
    try:
        from parsers.pptx_parser import extract_pptx_text

        return extract_pptx_text(io.BytesIO(raw_bytes))
    except Exception as e:
        log.debug("  PPTX bytes parse failed for %s: %s", filename, e)
        return ""
