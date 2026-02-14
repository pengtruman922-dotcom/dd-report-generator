"""Shared OCR utility using RapidOCR (singleton to avoid loading models multiple times)."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_ocr_engine = None

# Skip images smaller than this (likely icons/bullets/logos)
MIN_IMAGE_BYTES = 10_000  # 10 KB


def ocr_image(img_bytes: bytes) -> str:
    """OCR a single image and return extracted text. Returns '' on failure."""
    if len(img_bytes) < MIN_IMAGE_BYTES:
        return ""

    global _ocr_engine
    try:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()

        result, _ = _ocr_engine(img_bytes)
        if result:
            return "\n".join([item[1] for item in result])
    except ImportError:
        log.warning("rapidocr-onnxruntime not installed, skipping OCR")
    except Exception:
        log.exception("OCR failed for image (%d bytes)", len(img_bytes))
    return ""
