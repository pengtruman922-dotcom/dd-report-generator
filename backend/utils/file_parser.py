"""Unified file parser for v3.0 - extracts text from various file formats."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def parse_attachment(file_path: str | Path) -> dict[str, Any]:
    """Parse an attachment file and return extracted content.

    Args:
        file_path: Path to the file

    Returns:
        {
            "filename": "example.pdf",
            "file_type": "pdf",
            "text": "extracted text content",
            "error": "error message if parsing failed"
        }
    """
    file_path = Path(file_path)
    filename = file_path.name
    suffix = file_path.suffix.lower()

    result = {
        "filename": filename,
        "file_type": suffix[1:] if suffix else "unknown",
        "text": "",
        "error": None,
    }

    try:
        if suffix == ".pdf":
            with file_path.open("rb") as fp:
                header = fp.read(4)
            if header != b"%PDF":
                result["error"] = "PDF 文件头无效，可能是加密/受保护文件，无法提取文本"
                return result
            result["text"] = _parse_pdf(file_path)
        elif suffix in (".docx", ".doc"):
            result["text"] = _parse_docx(file_path)
        elif suffix in (".pptx", ".ppt"):
            result["text"] = _parse_pptx(file_path)
        elif suffix in (".xlsx", ".xls"):
            result["text"] = _parse_excel_text(file_path)
        elif suffix in (".txt", ".md"):
            result["text"] = file_path.read_text(encoding="utf-8", errors="ignore")
        elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            # 图片保留 base64，不提取文本
            result["text"] = f"[图片文件: {filename}]"
            result["base64"] = _image_to_base64(file_path)
        else:
            result["error"] = f"不支持的文件类型: {suffix}"
    except Exception as e:
        log.error(f"Failed to parse {filename}: {e}")
        result["error"] = str(e)

    return result


def _parse_pdf(file_path: Path) -> str:
    """Extract text from PDF."""
    from parsers.pdf_parser import extract_pdf_text

    return extract_pdf_text(str(file_path))


def _parse_docx(file_path: Path) -> str:
    """Extract text from DOCX."""
    from parsers.docx_parser import extract_docx_text

    return extract_docx_text(str(file_path))


def _parse_pptx(file_path: Path) -> str:
    """Extract text from PPTX."""
    from parsers.pptx_parser import extract_pptx_text

    return extract_pptx_text(str(file_path))


def _parse_excel_text(file_path: Path) -> str:
    """Extract text from Excel (all sheets, all cells).

    This is different from excel_parser.parse_excel() which parses structured data.
    Here we just extract all text for IntakeAgent to read.
    """
    import pandas as pd

    try:
        # Read all sheets
        excel_file = pd.ExcelFile(file_path, engine="openpyxl")
        all_text = []

        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)

            # Sheet header
            all_text.append(f"## {sheet_name}\n")

            # Convert to text: headers + rows
            # Replace NaN with empty string
            df = df.fillna("")

            # Headers
            headers = " | ".join(str(col) for col in df.columns)
            all_text.append(headers + "\n")

            # Rows (limit to first 100 rows to avoid too much text)
            for idx, row in df.head(100).iterrows():
                row_text = " | ".join(str(val) for val in row.values)
                all_text.append(row_text + "\n")

            if len(df) > 100:
                all_text.append(f"\n... (共 {len(df)} 行，仅显示前 100 行)\n")

            all_text.append("\n")

        return "".join(all_text)

    except Exception as e:
        log.error(f"Failed to extract text from Excel {file_path}: {e}")
        return f"[Excel 文件解析失败: {e}]"


def _image_to_base64(file_path: Path) -> str:
    """Convert image to base64 string."""
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        log.error(f"Failed to convert image to base64: {e}")
        return ""


def extract_text_batch(file_paths: list[str | Path]) -> dict[str, dict[str, Any]]:
    """Parse multiple files and return a dict of filename -> parsed result.

    Args:
        file_paths: List of file paths

    Returns:
        {
            "example.pdf": {filename, file_type, text, error},
            "data.xlsx": {...},
            ...
        }
    """
    results = {}
    for fp in file_paths:
        parsed = parse_attachment(fp)
        results[parsed["filename"]] = parsed
    return results
