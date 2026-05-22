"""Extract text from PDF files.

Strategy:
  1. PyMuPDF text extraction (best for native text PDFs)
  2. pdfplumber fallback (alternative text extractor)
  3. OCR fallback via rapidocr-onnxruntime (for scanned / image-based PDFs)
     - Primary: PyMuPDF renders pages to images for OCR
     - Secondary: pdfplumber renders pages to images for OCR (handles non-standard PDFs)

The OCR path is triggered when text extraction yields too little text
relative to the number of pages (likely scanned images).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from parsers.ocr_utils import ocr_image

log = logging.getLogger(__name__)

# Minimum average chars per page to consider text extraction sufficient.
# If below this threshold, OCR is attempted.
_MIN_CHARS_PER_PAGE = 80


def _needs_ocr(page_count: int, text_len: int) -> bool:
    if page_count > 0:
        return text_len / page_count < _MIN_CHARS_PER_PAGE
    return text_len < 100


def extract_pdf_text(file_path: str | Path) -> str:
    """Return the full text of a PDF file."""
    file_path = Path(file_path)
    log.info("Extracting text from PDF: %s (%d bytes)", file_path.name, file_path.stat().st_size)

    text = _try_pymupdf(file_path)
    pymupdf_len = len((text or "").strip())
    log.info("  PyMuPDF: %d chars", pymupdf_len)

    if not text or pymupdf_len < 100:
        text = _try_pdfplumber(file_path)
        pdfplumber_len = len((text or "").strip())
        log.info("  pdfplumber: %d chars", pdfplumber_len)

    # Check if text extraction yielded enough content
    page_count = _get_page_count(file_path)
    text_len = len((text or "").strip())
    log.info("  page_count=%d, text_len=%d", page_count, text_len)

    need_ocr = _needs_ocr(page_count, text_len)
    if page_count > 0 and text_len / page_count < _MIN_CHARS_PER_PAGE:
        log.info(
            "  Text extraction insufficient (%d chars / %d pages = %.0f avg). Attempting OCR...",
            text_len, page_count, text_len / page_count,
        )
    elif page_count == 0 and text_len < 100:
        # Page count unknown (file couldn't be opened normally) AND text is minimal
        # Still try OCR as last resort
        log.info("  Cannot determine page count and text is minimal (%d chars). Attempting OCR...", text_len)

    if need_ocr:
        ocr_text = _try_ocr(file_path)
        ocr_len = len((ocr_text or "").strip())
        log.info("  OCR result: %d chars", ocr_len)
        if ocr_text and ocr_len > text_len:
            log.info("  Using OCR text (%d chars > %d chars from extraction)", ocr_len, text_len)
            text = ocr_text

    final_len = len((text or "").strip())
    log.info("  FINAL result for %s: %d chars", file_path.name, final_len)
    return text


def extract_pdf_text_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Return the full text of a PDF from uploaded bytes.

    This mirrors `extract_pdf_text` so intake-time parsing and v4 pipeline
    parsing share the same extraction policy.
    """
    log.info("Extracting text from PDF bytes: %s (%d bytes)", filename, len(raw_bytes))

    text, page_count = _try_pymupdf_bytes(raw_bytes)
    pymupdf_len = len((text or "").strip())
    log.info("  PyMuPDF (bytes): %d chars from %d pages", pymupdf_len, page_count)

    if not text or pymupdf_len < 100:
        plumber_text, plumber_pages = _try_pdfplumber_bytes(raw_bytes)
        plumber_len = len((plumber_text or "").strip())
        log.info("  pdfplumber (bytes): %d chars from %d pages", plumber_len, plumber_pages)
        if plumber_len > pymupdf_len:
            text = plumber_text
        if plumber_pages:
            page_count = plumber_pages

    text_len = len((text or "").strip())
    log.info("  page_count=%d, text_len=%d", page_count, text_len)

    if _needs_ocr(page_count, text_len):
        if page_count > 0:
            log.info(
                "  Text extraction insufficient (%d chars / %d pages = %.0f avg). Attempting OCR...",
                text_len, page_count, text_len / page_count,
            )
        else:
            log.info("  Cannot determine page count and text is minimal (%d chars). Attempting OCR...", text_len)

        ocr_text = _try_ocr_bytes(raw_bytes)
        ocr_len = len((ocr_text or "").strip())
        log.info("  OCR (bytes) result: %d chars", ocr_len)
        if ocr_text and ocr_len > text_len:
            log.info("  Using OCR text from bytes (%d chars > %d chars from extraction)", ocr_len, text_len)
            text = ocr_text

    final_len = len((text or "").strip())
    log.info("  FINAL result for %s: %d chars", filename, final_len)
    return text


def _get_page_count(file_path: str | Path) -> int:
    """Get number of pages in a PDF."""
    # Try PyMuPDF first
    try:
        import fitz
        doc = fitz.open(str(file_path))
        count = doc.page_count
        doc.close()
        return count
    except Exception:
        pass

    # Fallback: try pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            return len(pdf.pages)
    except Exception:
        pass

    return 0


def _try_pymupdf(file_path: str | Path) -> str:
    try:
        import fitz

        doc = fitz.open(str(file_path))
        parts: list[str] = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        return "\n\n".join(parts)
    except Exception as e:
        log.debug("PyMuPDF failed for %s: %s", file_path, e)
        return ""


def _try_pdfplumber(file_path: str | Path) -> str:
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    parts.append(page_text)
        return "\n\n".join(parts)
    except Exception as e:
        log.debug("pdfplumber failed for %s: %s", file_path, e)
        return ""


def _try_pymupdf_bytes(raw_bytes: bytes) -> tuple[str, int]:
    try:
        import fitz

        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        parts = [page.get_text() for page in doc]
        page_count = doc.page_count
        doc.close()
        return "\n\n".join(parts), page_count
    except Exception:
        log.debug("PyMuPDF bytes extraction failed", exc_info=True)
        return "", 0


def _try_pdfplumber_bytes(raw_bytes: bytes) -> tuple[str, int]:
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    parts.append(page_text)
            return "\n\n".join(parts), len(pdf.pages)
    except Exception:
        log.debug("pdfplumber bytes extraction failed", exc_info=True)
        return "", 0


def _try_ocr(file_path: str | Path) -> str:
    """OCR fallback for scanned / image-based PDFs using RapidOCR."""
    # Try PyMuPDF-based OCR first (renders pages to images)
    text = _try_ocr_via_pymupdf(file_path)
    if text and len(text.strip()) > 100:
        return text

    # Fallback: pdfplumber-based OCR (handles non-standard PDF formats)
    log.info("PyMuPDF OCR failed or returned too little, trying pdfplumber OCR...")
    text = _try_ocr_via_pdfplumber(file_path)
    return text


def _try_ocr_bytes(raw_bytes: bytes) -> str:
    """OCR fallback for in-memory PDF bytes."""
    text = _try_ocr_via_pymupdf_bytes(raw_bytes)
    if text and len(text.strip()) > 100:
        return text

    log.info("PyMuPDF bytes OCR failed or returned too little, trying pdfplumber bytes OCR...")
    return _try_ocr_via_pdfplumber_bytes(raw_bytes)


def _try_ocr_via_pymupdf(file_path: str | Path) -> str:
    """OCR using PyMuPDF to render pages as images."""
    try:
        import fitz
    except ImportError:
        return ""

    try:
        doc = fitz.open(str(file_path))

        max_pages = min(doc.page_count, 50)
        # Lower DPI for large documents to keep processing time reasonable
        dpi = 200 if max_pages <= 20 else 150

        parts: list[str] = []
        for i in range(max_pages):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")

            page_text = ocr_image(img_bytes)
            if page_text.strip():
                parts.append(page_text)

            if (i + 1) % 10 == 0:
                log.info("OCR (PyMuPDF) progress: %d/%d pages", i + 1, max_pages)

        doc.close()
        total_chars = sum(len(p) for p in parts)
        log.info("OCR (PyMuPDF) complete: %d pages processed, %d chars extracted", max_pages, total_chars)
        return "\n\n".join(parts)
    except Exception:
        log.debug("OCR via PyMuPDF failed for %s", file_path, exc_info=True)
        return ""


def _try_ocr_via_pymupdf_bytes(raw_bytes: bytes) -> str:
    """OCR using PyMuPDF to render uploaded PDF bytes as images."""
    try:
        import fitz
    except ImportError:
        return ""

    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        max_pages = min(doc.page_count, 50)
        dpi = 200 if max_pages <= 20 else 150

        parts: list[str] = []
        for i in range(max_pages):
            pix = doc[i].get_pixmap(dpi=dpi)
            page_text = ocr_image(pix.tobytes("png"))
            if page_text.strip():
                parts.append(page_text)

            if (i + 1) % 10 == 0:
                log.info("OCR (PyMuPDF bytes) progress: %d/%d pages", i + 1, max_pages)

        doc.close()
        total_chars = sum(len(p) for p in parts)
        log.info("OCR (PyMuPDF bytes) complete: %d pages processed, %d chars extracted", max_pages, total_chars)
        return "\n\n".join(parts)
    except Exception:
        log.debug("OCR via PyMuPDF bytes failed", exc_info=True)
        return ""


def _try_ocr_via_pdfplumber(file_path: str | Path) -> str:
    """OCR using pdfplumber to render pages as images (handles non-standard PDFs)."""
    try:
        import pdfplumber
    except ImportError:
        log.debug("pdfplumber not available for OCR fallback")
        return ""

    try:
        parts: list[str] = []

        with pdfplumber.open(file_path) as pdf:
            max_pages = min(len(pdf.pages), 50)
            dpi = 200 if max_pages <= 20 else 150

            for i, page in enumerate(pdf.pages[:max_pages]):
                try:
                    img = page.to_image(resolution=dpi)
                    # Convert to PNG bytes
                    buf = io.BytesIO()
                    img.original.save(buf, format="PNG")
                    page_text = ocr_image(buf.getvalue())
                    if page_text.strip():
                        parts.append(page_text)
                except Exception:
                    log.debug("OCR (pdfplumber) failed for page %d of %s", i + 1, file_path)

                if (i + 1) % 10 == 0:
                    log.info("OCR (pdfplumber) progress: %d/%d pages", i + 1, max_pages)

        total_chars = sum(len(p) for p in parts)
        log.info("OCR (pdfplumber) complete: %d pages processed, %d chars extracted", max_pages, total_chars)
        return "\n\n".join(parts)
    except Exception:
        log.debug("OCR via pdfplumber failed for %s", file_path, exc_info=True)
        return ""


def _try_ocr_via_pdfplumber_bytes(raw_bytes: bytes) -> str:
    """OCR using pdfplumber to render uploaded PDF bytes as images."""
    try:
        import pdfplumber
    except ImportError:
        log.debug("pdfplumber not available for bytes OCR fallback")
        return ""

    try:
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            max_pages = min(len(pdf.pages), 50)
            dpi = 200 if max_pages <= 20 else 150

            for i, page in enumerate(pdf.pages[:max_pages]):
                try:
                    img = page.to_image(resolution=dpi)
                    buf = io.BytesIO()
                    img.original.save(buf, format="PNG")
                    page_text = ocr_image(buf.getvalue())
                    if page_text.strip():
                        parts.append(page_text)
                except Exception:
                    log.debug("OCR (pdfplumber bytes) failed for page %d", i + 1)

                if (i + 1) % 10 == 0:
                    log.info("OCR (pdfplumber bytes) progress: %d/%d pages", i + 1, max_pages)

        total_chars = sum(len(p) for p in parts)
        log.info("OCR (pdfplumber bytes) complete: %d pages processed, %d chars extracted", max_pages, total_chars)
        return "\n\n".join(parts)
    except Exception:
        log.debug("OCR via pdfplumber bytes failed", exc_info=True)
        return ""
