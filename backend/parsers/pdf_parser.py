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

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Minimum average chars per page to consider text extraction sufficient.
# If below this threshold, OCR is attempted.
_MIN_CHARS_PER_PAGE = 80


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

    need_ocr = False
    if page_count > 0 and text_len / page_count < _MIN_CHARS_PER_PAGE:
        need_ocr = True
        log.info(
            "  Text extraction insufficient (%d chars / %d pages = %.0f avg). Attempting OCR...",
            text_len, page_count, text_len / page_count,
        )
    elif page_count == 0 and text_len < 100:
        # Page count unknown (file couldn't be opened normally) AND text is minimal
        # Still try OCR as last resort
        need_ocr = True
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


def _try_ocr(file_path: str | Path) -> str:
    """OCR fallback for scanned / image-based PDFs using RapidOCR."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        log.warning("rapidocr-onnxruntime not installed, skipping OCR")
        return ""

    # Try PyMuPDF-based OCR first (renders pages to images)
    text = _try_ocr_via_pymupdf(file_path)
    if text and len(text.strip()) > 100:
        return text

    # Fallback: pdfplumber-based OCR (handles non-standard PDF formats)
    log.info("PyMuPDF OCR failed or returned too little, trying pdfplumber OCR...")
    text = _try_ocr_via_pdfplumber(file_path)
    return text


def _try_ocr_via_pymupdf(file_path: str | Path) -> str:
    """OCR using PyMuPDF to render pages as images."""
    try:
        import fitz
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return ""

    try:
        ocr_engine = RapidOCR()
        doc = fitz.open(str(file_path))

        max_pages = min(doc.page_count, 50)
        # Lower DPI for large documents to keep processing time reasonable
        dpi = 200 if max_pages <= 20 else 150

        parts: list[str] = []
        for i in range(max_pages):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")

            result, _ = ocr_engine(img_bytes)
            if result:
                page_text = "\n".join([item[1] for item in result])
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


def _try_ocr_via_pdfplumber(file_path: str | Path) -> str:
    """OCR using pdfplumber to render pages as images (handles non-standard PDFs)."""
    try:
        import pdfplumber
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image
        import io
    except ImportError:
        log.debug("pdfplumber or PIL not available for OCR fallback")
        return ""

    try:
        ocr_engine = RapidOCR()
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
                    img_bytes = buf.getvalue()

                    result, _ = ocr_engine(img_bytes)
                    if result:
                        page_text = "\n".join([item[1] for item in result])
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
