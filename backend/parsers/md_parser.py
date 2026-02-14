"""Read Markdown attachment files."""

from __future__ import annotations

from pathlib import Path


def read_md(file_path: str | Path) -> str:
    """Return the contents of a Markdown file."""
    path = Path(file_path)
    return path.read_text(encoding="utf-8")
