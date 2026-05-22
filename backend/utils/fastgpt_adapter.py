"""FastGPT push adapter helpers for report chunks."""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_V3_CHUNK_LABELS = {
    "chunk0": "身份卡",
    "chunk1": "财务数据",
    "chunk2": "业务与竞争力",
    "chunk3": "行业与市场",
    "chunk4": "风险与合规",
    "chunk5": "交易条件",
    "chunk6": "客户与供应链",
    "chunk7": "跟进动态",
}
_V4_CHUNK_LABELS = {
    "info": "标的信息",
    "tracking": "跟进动态",
}


def _dedupe_indexes(indexes: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in indexes:
        text = str(item.get("text", "")).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append({"text": text})
    return result


def build_fastgpt_chunks_v3(
    report_id: str,
    chunks: dict[str, dict],
    company_name: str,
    bd_code: str,
) -> list[dict[str, Any]]:
    """Build legacy FastGPT chunks from v3 report chunks."""
    fastgpt_chunks = []

    for chunk_id in ["chunk0", "chunk1", "chunk2", "chunk3", "chunk4", "chunk5", "chunk6", "chunk7"]:
        if chunk_id not in chunks:
            continue

        chunk = chunks[chunk_id]
        label = _V3_CHUNK_LABELS.get(chunk_id, chunk_id)
        summary = chunk.get("summary", "")
        content = chunk.get("content", "")
        index_tags = chunk.get("index_tags", [])

        if not content:
            continue

        indexes = [
            {"text": company_name},
            {"text": bd_code},
            {"text": label},
            {"text": chunk_id},
        ]
        if summary:
            indexes.append({"text": summary})
        indexes.extend({"text": str(tag)} for tag in index_tags)

        fastgpt_chunks.append({
            "q": content,
            "a": "",
            "indexes": _dedupe_indexes(indexes),
        })

    return fastgpt_chunks


def build_fastgpt_chunks_v4(
    report_id: str,
    chunks: dict[str, dict],
    company_name: str,
    bd_code: str,
    info_summary: str | None = None,
    info_index_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build FastGPT chunks from v4 report chunks. Only info_chunk is pushed."""
    info_chunk = chunks.get("info")
    if not info_chunk or not info_chunk.get("content"):
        return []

    indexes = [
        {"text": company_name},
        {"text": bd_code},
        {"text": _V4_CHUNK_LABELS["info"]},
        {"text": "info"},
    ]
    summary = (info_summary or info_chunk.get("summary") or "").strip()
    if summary:
        indexes.append({"text": summary})
    source_tags = [*(info_chunk.get("index_tags", []) or []), *(info_index_tags or [])]
    for tag in source_tags:
        indexes.append({"text": str(tag)})

    return [{
        "q": info_chunk.get("content", ""),
        "a": "",
        "indexes": _dedupe_indexes(indexes),
    }]


def load_chunks_v3(report_id: str) -> dict[str, dict]:
    """Load chunks from report_chunks table."""
    from db import get_db

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT chunk_id, summary, content, index_tags FROM report_chunks WHERE report_id = ?",
            (report_id,)
        ).fetchall()

        chunks = {}
        for row in rows:
            try:
                index_tags = json.loads(row["index_tags"]) if row["index_tags"] else []
            except Exception:
                index_tags = []

            chunks[row["chunk_id"]] = {
                "summary": row["summary"] or "",
                "content": row["content"] or "",
                "index_tags": index_tags,
            }

        return chunks

    finally:
        conn.close()
