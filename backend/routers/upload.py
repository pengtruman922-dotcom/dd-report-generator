"""Upload endpoints: Excel file, PDF/MD attachments, and manual input."""

from __future__ import annotations

import io
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from config import UPLOAD_DIR
from parsers.excel_parser import parse_excel, get_company_list, FIELD_LABELS

log = logging.getLogger(__name__)

router = APIRouter()

# In-memory store: session_id → { excel_path, companies, attachments, parsed_texts }
_sessions: dict[str, dict] = {}


def get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise HTTPException(404, f"Session {session_id} not found")
    return _sessions[session_id]


class ManualInputRequest(BaseModel):
    """Manual input fields - bd_code, company_name, project_name required."""
    bd_code: str
    company_name: str
    project_name: str
    revenue_yuan: str | None = None
    valuation_yuan: str | None = None
    net_profit_yuan: str | None = None
    industry: str | None = None
    stock_code: str | None = None
    valuation_date: str | None = None
    website: str | None = None
    is_listed: str | None = None
    description: str | None = None
    company_intro: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    revenue: str | None = None
    net_profit: str | None = None
    industry_tags: str | None = None
    referral_status: str | None = None
    is_traded: str | None = None
    dept_primary: str | None = None
    dept_owner: str | None = None
    remarks: str | None = None


@router.post("/excel")
async def upload_excel(file: UploadFile = File(...)):
    """Upload an Excel file; returns parsed company list + session id."""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Please upload an .xlsx or .xls file")

    session_id = uuid.uuid4().hex[:12]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    file_path = session_dir / file.filename
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    try:
        companies = get_company_list(str(file_path))
        all_rows = parse_excel(str(file_path))
    except Exception as e:
        raise HTTPException(422, f"Failed to parse Excel: {e}")

    _sessions[session_id] = {
        "excel_path": str(file_path),
        "companies": companies,
        "all_rows": all_rows,
        "attachments": {},      # bd_code → [file_paths]
        "parsed_texts": {},     # bd_code → [(filename, text)]
    }

    return {
        "session_id": session_id,
        "company_count": len(companies),
        "companies": companies,
    }


@router.post("/manual")
async def manual_input(req: ManualInputRequest):
    """Create a session from manually entered data (no Excel needed)."""
    session_id = uuid.uuid4().hex[:12]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    row = req.model_dump()
    # Remove None values
    row = {k: v for k, v in row.items() if v is not None}

    _sessions[session_id] = {
        "excel_path": None,
        "companies": [
            {
                "bd_code": req.bd_code,
                "company_name": req.company_name,
                "project_name": req.project_name,
            }
        ],
        "all_rows": [row],
        "attachments": {},
        "parsed_texts": {},
    }

    return {
        "session_id": session_id,
        "bd_code": req.bd_code,
        "company_name": req.company_name,
        "project_name": req.project_name,
    }


@router.get("/fields")
async def get_field_definitions():
    """Return the field definitions for manual input form."""
    required = ["bd_code", "company_name", "project_name"]
    fields = []
    for en_key, cn_label in FIELD_LABELS.items():
        # Skip attachment-only fields
        if en_key in ("intro_attachment", "annual_report_attachment"):
            continue
        fields.append({
            "key": en_key,
            "label": cn_label,
            "required": en_key in required,
        })
    return {"fields": fields}


def _parse_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Parse attachment text from raw in-memory bytes (before any disk encryption).

    This avoids issues with filesystem-level encryption (e.g. TSD) that may
    alter files after they are written to disk.
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return _parse_pdf_from_bytes(filename, raw_bytes)
    elif ext in (".md", ".txt"):
        return raw_bytes.decode("utf-8", errors="replace")
    elif ext == ".docx":
        return _parse_docx_from_bytes(filename, raw_bytes)
    elif ext == ".pptx":
        return _parse_pptx_from_bytes(filename, raw_bytes)
    return ""


def _parse_pdf_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Parse PDF from in-memory bytes using PyMuPDF, pdfplumber, and OCR."""
    text = ""

    # 1. Try PyMuPDF
    try:
        import fitz
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        parts = [page.get_text() for page in doc]
        page_count = doc.page_count
        doc.close()
        text = "\n\n".join(parts)
        log.info("  PyMuPDF (bytes): %d chars from %d pages", len(text.strip()), page_count)
    except Exception as e:
        log.debug("  PyMuPDF (bytes) failed for %s: %s", filename, e)
        page_count = 0

    # 2. Fallback: pdfplumber
    if len(text.strip()) < 100:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                page_count = len(pdf.pages)
                parts = []
                for page in pdf.pages:
                    pt = page.extract_text()
                    if pt:
                        parts.append(pt)
                text = "\n\n".join(parts)
                log.info("  pdfplumber (bytes): %d chars from %d pages", len(text.strip()), page_count)
        except Exception as e:
            log.debug("  pdfplumber (bytes) failed for %s: %s", filename, e)

    # 3. OCR if text extraction insufficient
    text_len = len(text.strip())
    need_ocr = (
        (page_count > 0 and text_len / page_count < 80)
        or (page_count == 0 and text_len < 100)
    )

    if need_ocr:
        log.info("  Text insufficient (%d chars), attempting OCR for %s...", text_len, filename)
        ocr_text = _ocr_pdf_from_bytes(raw_bytes, page_count)
        if ocr_text and len(ocr_text.strip()) > text_len:
            log.info("  OCR yielded %d chars (vs %d from text extraction)", len(ocr_text.strip()), text_len)
            text = ocr_text

    return text


def _ocr_pdf_from_bytes(raw_bytes: bytes, known_page_count: int) -> str:
    """OCR a PDF from in-memory bytes."""
    # Try PyMuPDF rendering first
    try:
        import fitz
        from rapidocr_onnxruntime import RapidOCR

        ocr_engine = RapidOCR()
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        max_pages = min(doc.page_count, 50)
        dpi = 200 if max_pages <= 20 else 150

        parts: list[str] = []
        for i in range(max_pages):
            pix = doc[i].get_pixmap(dpi=dpi)
            result, _ = ocr_engine(pix.tobytes("png"))
            if result:
                page_text = "\n".join([item[1] for item in result])
                if page_text.strip():
                    parts.append(page_text)
        doc.close()
        total = sum(len(p) for p in parts)
        log.info("  OCR (PyMuPDF bytes): %d pages → %d chars", max_pages, total)
        if total > 100:
            return "\n\n".join(parts)
    except Exception as e:
        log.debug("  OCR via PyMuPDF bytes failed: %s", e)

    # Fallback: pdfplumber rendering
    try:
        import pdfplumber
        from rapidocr_onnxruntime import RapidOCR

        ocr_engine = RapidOCR()
        parts = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            max_pages = min(len(pdf.pages), 50)
            dpi = 200 if max_pages <= 20 else 150
            for i, page in enumerate(pdf.pages[:max_pages]):
                try:
                    img = page.to_image(resolution=dpi)
                    buf = io.BytesIO()
                    img.original.save(buf, format="PNG")
                    result, _ = ocr_engine(buf.getvalue())
                    if result:
                        page_text = "\n".join([item[1] for item in result])
                        if page_text.strip():
                            parts.append(page_text)
                except Exception:
                    pass
        total = sum(len(p) for p in parts)
        log.info("  OCR (pdfplumber bytes): %d pages → %d chars", max_pages, total)
        return "\n\n".join(parts)
    except Exception as e:
        log.debug("  OCR via pdfplumber bytes failed: %s", e)

    return ""


def _parse_docx_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Parse DOCX from in-memory bytes."""
    try:
        from parsers.docx_parser import extract_docx_text
        # python-docx accepts file-like objects
        return extract_docx_text(io.BytesIO(raw_bytes))
    except Exception as e:
        log.debug("  DOCX bytes parse failed for %s: %s", filename, e)
        return ""


def _parse_pptx_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Parse PPTX from in-memory bytes."""
    try:
        from parsers.pptx_parser import extract_pptx_text
        return extract_pptx_text(io.BytesIO(raw_bytes))
    except Exception as e:
        log.debug("  PPTX bytes parse failed for %s: %s", filename, e)
        return ""


@router.post("/attachments")
async def upload_attachments(
    session_id: str,
    bd_code: str,
    files: list[UploadFile] = File(...),
):
    """Upload PDF/MD attachments for a specific company.

    Files are parsed immediately from in-memory bytes (before writing to disk)
    to avoid filesystem-level encryption (e.g. TSD) corrupting the saved files.
    """
    session = get_session(session_id)
    session_dir = UPLOAD_DIR / session_id / bd_code
    session_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    parsed: list[dict] = []
    skipped: list[str] = []

    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in (".pdf", ".md", ".txt", ".docx", ".pptx"):
            skipped.append(f.filename)
            continue

        # Read raw bytes from upload stream (before any disk encryption)
        raw_bytes = await f.read()
        if not raw_bytes:
            skipped.append(f.filename)
            continue

        # Save to disk (for reference/backup)
        dest = session_dir / f.filename
        with open(dest, "wb") as out:
            out.write(raw_bytes)
        saved.append(str(dest))

        # Parse text from in-memory bytes immediately
        log.info("Parsing attachment from memory: %s (%d bytes)", f.filename, len(raw_bytes))
        try:
            text = _parse_from_bytes(f.filename, raw_bytes)
            text_len = len(text.strip()) if text else 0
            log.info("Parsed %s: %d chars", f.filename, text_len)
            parsed.append({"filename": f.filename, "text_length": text_len})

            if text and text.strip():
                session.setdefault("parsed_texts", {}).setdefault(bd_code, []).append(
                    (f.filename, text)
                )
            else:
                log.warning("Attachment parsed but empty: %s", f.filename)
        except Exception as e:
            log.exception("Failed to parse attachment from memory: %s", f.filename)
            parsed.append({"filename": f.filename, "text_length": 0, "error": str(e)})

    session["attachments"].setdefault(bd_code, []).extend(saved)

    return {
        "bd_code": bd_code,
        "uploaded": len(saved),
        "files": saved,
        "parsed": parsed,
        "skipped": skipped,
    }


@router.get("/session/{session_id}")
async def get_session_info(session_id: str):
    """Return session metadata (companies, attachments)."""
    session = get_session(session_id)
    return {
        "session_id": session_id,
        "companies": session["companies"],
        "attachments": {k: len(v) for k, v in session["attachments"].items()},
    }


# Expose sessions dict for other routers
def get_sessions():
    return _sessions
