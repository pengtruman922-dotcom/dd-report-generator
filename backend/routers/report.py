"""Report generation, progress SSE, list, delete, and download endpoints."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import logging

from auth import get_current_user
from config import OUTPUT_DIR, load_settings, DEFAULT_FASTGPT_CONFIG
from db import get_db
from services.fastgpt_uploader import (
    push_report_to_fastgpt,
    delete_collection,
)

log = logging.getLogger(__name__)
from services.sse_manager import sse_manager

router = APIRouter()


class BatchDeleteRequest(BaseModel):
    report_ids: list[str]


class AttachmentUpdateRequest(BaseModel):
    attachment_filenames: list[str]
    note: str | None = None


class ChunkIndex(BaseModel):
    text: str


class ReportChunk(BaseModel):
    title: str
    q: str
    indexes: list[ChunkIndex] = []
    chunk_id: str | None = None
    summary: str | None = None
    content: str | None = None


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
_ALL_CHUNK_LABELS = {**_V3_CHUNK_LABELS, **_V4_CHUNK_LABELS}
_CHUNK_RENDER_ORDER = {"info": 0, "tracking": 1}
# Protected system fields that cannot be edited
_PROTECTED_META_KEYS = {
    "report_id", "bd_code", "status", "score", "rating",
    "created_at", "file_size", "owner", "push_records",
    "push_status", "push_info", "attachments",
}

_DATE_RE = re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?")
_AMOUNT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>亿元|亿|万元|万|元)")


def _build_attachment_update_log_fields(updated_chunks: list[str], attachments_used: list[str]) -> dict:
    if not updated_chunks:
        return {
            "附件更新": {
                "old": "报告正文未变更",
                "new": "已检查新附件，但未识别到需要更新的章节",
            }
        }
    attachment_text = "、".join(attachments_used) if attachments_used else "本次上传附件"
    return {
        _ALL_CHUNK_LABELS.get(chunk_id, chunk_id): {
            "old": "保留原有内容",
            "new": f"依据 {attachment_text} 增量更新",
        }
        for chunk_id in updated_chunks
    }


def _render_markdown_from_chunks(
    company_name: str,
    report_format: str,
    chunk_rows: list[dict[str, str]],
) -> str:
    title = "标的信息" if report_format == "v4" else "尽调报告"
    ordered_rows = sorted(
        chunk_rows,
        key=lambda cr: _CHUNK_RENDER_ORDER.get(cr["chunk_id"], 99),
    )
    parts = [f"# {company_name} {title}\n"]
    for row in ordered_rows:
        parts.append(f"\n## {row['label']}\n")
        if row.get("summary"):
            parts.append(f"\n**摘要**: {row['summary']}\n")
        parts.append(f"\n{row.get('content') or ''}\n")
    return "".join(parts)


def _iter_meaningful_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[#>\-\*\+\d\.\)\(、\s]+", "", line).strip()
        if line:
            lines.append(line)
    return lines


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _amount_match_to_yuan(match: re.Match[str]) -> str | None:
    unit = match.group("unit")
    try:
        amount = Decimal(match.group("value"))
    except (InvalidOperation, TypeError):
        return None
    multiplier = {
        "亿元": Decimal("100000000"),
        "亿": Decimal("100000000"),
        "万元": Decimal("10000"),
        "万": Decimal("10000"),
        "元": Decimal("1"),
    }.get(unit)
    if multiplier is None:
        return None
    return str(int(amount * multiplier))


def _extract_latest_fact_from_text(
    text: str,
    keywords: tuple[str, ...],
) -> tuple[str | None, str | None]:
    fallback_date = None
    for match in _DATE_RE.finditer(text or ""):
        fallback_date = _normalize_date(match.group(0))

    latest_amount = None
    latest_date = None
    for line in _iter_meaningful_lines(text):
        if not any(keyword in line for keyword in keywords):
            continue
        amount_matches = list(_AMOUNT_RE.finditer(line))
        if not amount_matches:
            continue
        latest_amount = _amount_match_to_yuan(amount_matches[-1])
        latest_date = _normalize_date(line) or fallback_date

    return latest_amount, latest_date


def _infer_transaction_status(*texts: str, fallback: str | None = None) -> str | None:
    combined = "\n".join(text for text in texts if text)
    if any(keyword in combined for keyword in ("已交易", "已成交", "完成交割", "完成交易", "成交")):
        return "已交易"
    if any(keyword in combined for keyword in ("终止", "不推进", "停止推进", "终止推进", "终止交易")):
        return "终止"
    if any(keyword in combined for keyword in ("暂停", "搁置", "暂缓")):
        return "暂停"
    if any(keyword in combined for keyword in ("推进", "继续推进", "沟通中", "接触中", "推进中")):
        return "推进中"
    return fallback


def _infer_deal_path(*texts: str, fallback: str | None = None) -> str | None:
    combined = "\n".join(text for text in texts if text)
    for candidate in ("股权转让", "资产转让", "增资扩股", "控股权转让", "债转股"):
        if candidate in combined:
            return candidate
    return fallback


def _infer_willingness(*texts: str, fallback: str | None = None) -> str | None:
    combined = "\n".join(text for text in texts if text)
    for candidate in ("继续推进", "出售意愿明确", "有意愿", "意愿较强", "观望", "暂不推进"):
        if candidate in combined:
            return candidate
    return fallback


def _build_referral_status_preview(text: str, fallback: str | None = None) -> str | None:
    lines = _iter_meaningful_lines(text)
    if not lines:
        return fallback
    return "\n".join(lines[:5])


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _rebuild_manual_v4_state(
    report_meta: dict[str, Any],
    existing_metadata: dict[str, Any],
    chunk_state: dict[str, dict[str, Any]],
    explicit_field_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    from services.index_builder import build_index_bundle

    explicit_field_overrides = explicit_field_overrides or {}
    normalized = {
        chunk_id: {
            "summary": (chunk.get("summary") or "").strip(),
            "content": (chunk.get("content") or "").strip(),
            "index_tags": [str(tag).strip() for tag in (chunk.get("index_tags") or []) if str(tag).strip()],
        }
        for chunk_id, chunk in chunk_state.items()
    }

    index_bundle = build_index_bundle(
        company_name=report_meta.get("company_name", ""),
        bd_code=report_meta.get("bd_code", ""),
        info_chunk=normalized.get("info"),
        tracking_chunk=normalized.get("tracking"),
    )
    if normalized.get("info"):
        normalized["info"]["summary"] = index_bundle.get("info_summary") or normalized["info"]["summary"]
        normalized["info"]["index_tags"] = index_bundle.get("info_index_tags", [])
    if normalized.get("tracking") and index_bundle.get("tracking_summary"):
        normalized["tracking"]["summary"] = index_bundle["tracking_summary"]

    existing_snapshot = existing_metadata.get("seller_fact_snapshot_json") or {}
    info_text = normalized.get("info", {}).get("content", "")
    tracking_text = normalized.get("tracking", {}).get("content", "")

    offer_yuan, offer_date = _extract_latest_fact_from_text(
        tracking_text,
        ("报价", "要价", "出价", "交易价格", "对价", "挂牌价"),
    )
    if not offer_yuan:
        offer_yuan, offer_date = _extract_latest_fact_from_text(
            info_text,
            ("报价", "要价", "出价", "交易价格", "对价", "挂牌价"),
        )

    valuation_yuan, valuation_date = _extract_latest_fact_from_text(
        info_text,
        ("估值", "投前估值", "投后估值", "整体估值"),
    )
    if not valuation_yuan:
        valuation_yuan, valuation_date = _extract_latest_fact_from_text(
            tracking_text,
            ("估值", "投前估值", "投后估值", "整体估值"),
        )

    offer_yuan_value = (
        _normalize_optional_text(explicit_field_overrides["offer_yuan"])
        if "offer_yuan" in explicit_field_overrides
        else offer_yuan or report_meta.get("offer_yuan") or existing_snapshot.get("offer_yuan")
    )
    offer_date_value = (
        _normalize_optional_text(explicit_field_overrides["offer_date"])
        if "offer_date" in explicit_field_overrides
        else offer_date or report_meta.get("offer_date") or existing_snapshot.get("offer_date")
    )
    valuation_yuan_value = (
        _normalize_optional_text(explicit_field_overrides["valuation_yuan"])
        if "valuation_yuan" in explicit_field_overrides
        else valuation_yuan or report_meta.get("valuation_yuan") or existing_snapshot.get("valuation_yuan")
    )
    valuation_date_value = (
        _normalize_optional_text(explicit_field_overrides["valuation_date"])
        if "valuation_date" in explicit_field_overrides
        else valuation_date or report_meta.get("valuation_date") or existing_snapshot.get("valuation_date")
    )

    referral_status = _build_referral_status_preview(
        tracking_text,
        fallback=report_meta.get("referral_status") or existing_snapshot.get("referral_status"),
    )
    if "referral_status" in explicit_field_overrides:
        referral_status = _normalize_optional_text(explicit_field_overrides["referral_status"])

    transaction_status = _infer_transaction_status(
        tracking_text,
        info_text,
        fallback=report_meta.get("is_traded") or existing_snapshot.get("transaction_status"),
    )
    if "is_traded" in explicit_field_overrides:
        transaction_status = _normalize_optional_text(explicit_field_overrides["is_traded"])

    field_updates = {
        "referral_status": referral_status,
        "is_traded": transaction_status,
        "offer_yuan": offer_yuan_value,
        "offer_date": offer_date_value,
        "valuation_yuan": valuation_yuan_value,
        "valuation_date": valuation_date_value,
    }

    snapshot = {
        **existing_snapshot,
        "offer_yuan": field_updates["offer_yuan"],
        "offer_date": field_updates["offer_date"],
        "valuation_yuan": field_updates["valuation_yuan"],
        "valuation_date": field_updates["valuation_date"],
        "deal_path": _infer_deal_path(
            tracking_text,
            info_text,
            fallback=existing_snapshot.get("deal_path"),
        ),
        "willingness": _infer_willingness(
            tracking_text,
            info_text,
            fallback=existing_snapshot.get("willingness"),
        ),
        "transaction_status": transaction_status,
        "transfer_ratio": existing_snapshot.get("transfer_ratio"),
        "blockers": existing_snapshot.get("blockers") or [],
        "nonpublic_risks": existing_snapshot.get("nonpublic_risks") or [],
    }

    metadata_updates = {
        "report_schema_version": "v4",
        "seller_fact_snapshot_json": snapshot,
        "tracking_summary": index_bundle.get("tracking_summary"),
        "info_summary": index_bundle.get("info_summary"),
        "info_index_tags": index_bundle.get("info_index_tags", []),
    }

    markdown = _render_markdown_from_chunks(
        report_meta.get("company_name") or report_meta.get("report_id") or "",
        "v4",
        [
            {
                "chunk_id": chunk_id,
                "label": _ALL_CHUNK_LABELS.get(chunk_id, chunk_id),
                "summary": chunk.get("summary", ""),
                "content": chunk.get("content", ""),
            }
            for chunk_id, chunk in normalized.items()
        ],
    )

    return normalized, metadata_updates, field_updates, markdown


def _get_report_paths(report_id: str) -> dict[str, Path]:
    """Get file paths for a report from database, with fallback to default paths."""
    from db import get_db

    # Try to get paths from database
    try:
        conn = get_db()
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT md_path, chunks_path, debug_dir, attachments_dir FROM reports WHERE report_id = ?",
            (report_id,)
        ).fetchone()
        conn.close()

        if row and row["md_path"]:
            return {
                "md": Path(row["md_path"]),
                "json": Path(row["md_path"]).parent / f"{report_id}.json",
                "debug": Path(row["debug_dir"]) if row["debug_dir"] else OUTPUT_DIR / f"{report_id}_debug",
                "attachments": Path(row["attachments_dir"]) if row["attachments_dir"] else OUTPUT_DIR / f"{report_id}_attachments",
            }
    except Exception as e:
        log.warning(f"Failed to get paths from database for {report_id}: {e}")

    # Fallback to default paths
    return {
        "md": OUTPUT_DIR / f"{report_id}.md",
        "json": OUTPUT_DIR / f"{report_id}.json",
        "debug": OUTPUT_DIR / f"{report_id}_debug",
        "attachments": OUTPUT_DIR / f"{report_id}_attachments",
    }


def _load_report_meta(report_id: str) -> dict | None:
    """Load metadata for a report from database, with JSON fallback."""
    from db import get_db

    # Try database first (primary source)
    try:
        conn = get_db()
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,)
        ).fetchone()
        conn.close()

        if row:
            # Convert row to dict
            meta = dict(row)
            meta.pop("locked_fields", None)
            # Parse JSON fields
            if meta.get("push_records"):
                try:
                    meta["push_records"] = json.loads(meta["push_records"])
                except:
                    meta["push_records"] = {}
            else:
                meta["push_records"] = {}
            if meta.get("attachments"):
                try:
                    meta["attachments"] = json.loads(meta["attachments"])
                except:
                    meta["attachments"] = []
            else:
                meta["attachments"] = []
            return meta
    except Exception as e:
        log.warning(f"Failed to load report {report_id} from database: {e}")

    # Fallback to JSON file
    paths = _get_report_paths(report_id)
    meta_path = paths["json"]
    md_path = paths["md"]

    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                meta.pop("locked_fields", None)
            return meta
        except Exception:
            pass

    # Fallback: build minimal metadata from the .md file
    if md_path.exists():
        try:
            content = md_path.read_text(encoding="utf-8")
            # Try to extract company name from first H1
            name_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            company_name = name_match.group(1).strip() if name_match else report_id
            # Try to extract score
            score_match = re.search(r"综合得分.*?\*\*\s*([\d.]+)\s*\*\*", content)
            score = float(score_match.group(1)) if score_match else None
            rating = None
            if score is not None:
                if score >= 8.0:
                    rating = "强烈推荐"
                elif score >= 6.5:
                    rating = "推荐"
                elif score >= 5.0:
                    rating = "谨慎推荐"
                elif score >= 3.5:
                    rating = "不推荐"
                else:
                    rating = "不建议"
            stat = md_path.stat()
            return {
                "report_id": report_id,
                "bd_code": "",
                "company_name": company_name,
                "industry": "",
                "province": "",
                "is_listed": "",
                "revenue": None,
                "net_profit": None,
                "score": score,
                "rating": rating,
                "status": "completed",
                "created_at": __import__("datetime").datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "file_size": stat.st_size,
            }
        except Exception:
            pass
    return None


def _artifact_paths_for_report(report_id: str) -> list[Path]:
    """Collect all local artifact paths that may belong to a report."""
    paths = _get_report_paths(report_id)
    candidates = [
        paths["md"],
        paths["json"],
        paths["debug"],
        paths["attachments"],
        OUTPUT_DIR / f"{report_id}.md",
        OUTPUT_DIR / f"{report_id}.json",
        OUTPUT_DIR / f"{report_id}_debug",
        OUTPUT_DIR / f"{report_id}_attachments",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _delete_report_artifacts(report_id: str) -> None:
    """Best-effort deletion of all local files/directories for a report."""
    for path in _artifact_paths_for_report(report_id):
        if path.is_dir():
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def _delete_report_related_rows(conn, report_id: str) -> None:
    """Delete rows that may survive in older DB schemas without FK cascade."""
    statements = [
        ("DELETE FROM report_chunks WHERE report_id = ?", (report_id,)),
        ("DELETE FROM intake_logs WHERE report_id = ?", (report_id,)),
        ("DELETE FROM pipeline_tasks WHERE report_id = ? OR task_id = ?", (report_id, report_id)),
        ("DELETE FROM reports WHERE report_id = ?", (report_id,)),
    ]
    for sql, params in statements:
        try:
            conn.execute(sql, params)
        except Exception as e:
            log.warning("Failed cleanup SQL for report %s: %s", report_id, e)


def _report_exists(report_id: str) -> bool:
    """Check whether a report exists in DB or local artifacts."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        conn.close()
        if row:
            return True
    except Exception:
        pass
    return _load_report_meta(report_id) is not None


def _has_chunks(report_id: str) -> bool:
    """Return whether a report has stored chunk records."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM report_chunks WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        conn.close()
        return bool(row and row["cnt"] > 0)
    except Exception:
        return False


def _collect_attachments(report_id: str) -> list[dict]:
    """Read attachment metadata from the report attachment directory."""
    files: list[dict] = []
    att_dir = _get_report_paths(report_id)["attachments"]
    if att_dir.exists():
        for fp in sorted(att_dir.iterdir()):
            if fp.is_file():
                files.append({"filename": fp.name, "size": fp.stat().st_size})
    return files


def _sync_attachments_db(report_id: str, attachments: list[dict]) -> None:
    """Persist attachments list to DB (source of truth for list page)."""
    try:
        conn = get_db()
        conn.execute(
            "UPDATE reports SET attachments = ?, updated_at = ? WHERE report_id = ?",
            (
                json.dumps(attachments, ensure_ascii=False),
                __import__("datetime").datetime.now().isoformat(),
                report_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Failed to update attachments in database for {report_id}: {e}")


def _build_v3_markdown(report_id: str) -> tuple[str, str] | None:
    """Build markdown from report chunks. Returns (company_name, markdown)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT company_name, report_format FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if not row:
            return None
        chunk_rows = conn.execute(
            "SELECT chunk_id, label, summary, content FROM report_chunks "
            "WHERE report_id = ? ORDER BY chunk_id",
            (report_id,),
        ).fetchall()
        if not chunk_rows:
            return None
        company_name = row["company_name"] or report_id
        report_format = row["report_format"] or "v3"
        markdown = _render_markdown_from_chunks(
            company_name,
            report_format,
            [dict(cr) for cr in chunk_rows],
        )
        return company_name, markdown
    finally:
        conn.close()


def _load_v3_chunks(report_id: str) -> list[dict]:
    """Load report chunks from DB for chunk editor / FastGPT push."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT chunk_id, label, summary, content, index_tags FROM report_chunks "
            "WHERE report_id = ? ORDER BY chunk_id",
            (report_id,),
        ).fetchall()
        chunks: list[dict] = []
        for row in rows:
            title = row["label"] or _ALL_CHUNK_LABELS.get(row["chunk_id"], row["chunk_id"])
            q_parts = []
            if row["summary"]:
                q_parts.append(f"摘要：{row['summary']}")
            if row["content"]:
                q_parts.append(row["content"])
            q_text = "\n\n".join(q_parts) if q_parts else ""
            try:
                raw_tags = json.loads(row["index_tags"]) if row["index_tags"] else []
            except Exception:
                raw_tags = []
            chunks.append({
                "title": title,
                "q": q_text,
                "indexes": [{"text": str(tag)} for tag in raw_tags if str(tag).strip()],
                "chunk_id": row["chunk_id"],
                "summary": row["summary"] or "",
                "content": row["content"] or "",
            })
        return chunks
    finally:
        conn.close()


def _compute_push_status(
    report_id: str,
    push_records: dict,
    dataset_id: str,
) -> tuple[str, dict | None]:
    """Compute push status relative to the current dataset_id.

    Returns (status, push_info) where status is one of:
      no_chunks, not_pushed, pushed, outdated
    """
    # Stopgap optimization: list page should not recompute chunk hashes per row.
    # We only derive a lightweight status from chunk presence and push records.
    if not _has_chunks(report_id):
        return "no_chunks", None
    if not dataset_id or dataset_id not in push_records:
        return "not_pushed", None
    record = push_records[dataset_id]
    return "pushed", record


@router.get("/list")
async def list_reports(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, description="Search in project/company/industry/tags/bd_code"),
    status: str | None = Query(None, description="Filter by status"),
    rating: str | None = Query(None, description="Filter by rating"),
    feasibility_rating: str | None = Query(None, description="Filter by feasibility rating (A-E)"),
    owner: str | None = Query(None, description="Filter by owner (admin only)"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_dir: str = Query("desc", regex="^(asc|desc)$", description="Sort direction"),
    user: dict = Depends(get_current_user)
):
    """List reports with server-side pagination, filtering, and sorting."""
    from db import get_db

    settings = load_settings()
    fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}
    dataset_id = fastgpt_cfg.get("dataset_id", "")

    # Try to load from database first
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Build WHERE clause
        where_clauses = []
        params = []

        # Ownership filtering
        if user["role"] != "admin":
            where_clauses.append("owner = ?")
            params.append(user["username"])
        elif owner:
            where_clauses.append("owner = ?")
            params.append(owner)

        # Status filter
        if status:
            where_clauses.append("status = ?")
            params.append(status)

        # Rating filter
        if rating:
            where_clauses.append("(rating = ? OR manual_rating = ?)")
            params.extend([rating, rating])
        if feasibility_rating:
            where_clauses.append("feasibility_rating = ?")
            params.append(feasibility_rating)

        # Search filter
        if search:
            where_clauses.append(
                "(project_name LIKE ? OR company_name LIKE ? OR bd_code LIKE ? OR industry LIKE ? OR industry_tags LIKE ?)"
            )
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])

        # Build WHERE clause string
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Get total count
        count_query = f"SELECT COUNT(*) FROM reports WHERE {where_sql}"
        total = cursor.execute(count_query, params).fetchone()[0]

        # Calculate pagination
        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size

        # Validate sort_by field and map to SQL order clause (prevent SQL injection)
        sort_dir_sql = "ASC" if sort_dir.lower() == "asc" else "DESC"
        allowed_sort_fields = {
            "created_at", "updated_at", "company_name", "project_name", "bd_code",
            "score", "rating", "status", "province", "industry", "estimated_cost",
            "feasibility_rating", "offer_or_valuation",
        }
        if sort_by not in allowed_sort_fields:
            sort_by = "created_at"

        if sort_by == "feasibility_rating":
            rating_order_expr = (
                "CASE feasibility_rating "
                "WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 "
                "WHEN 'D' THEN 4 WHEN 'E' THEN 5 ELSE NULL END"
            )
            order_clause = f"({rating_order_expr}) IS NULL, ({rating_order_expr}) {sort_dir_sql}"
        elif sort_by == "offer_or_valuation":
            offer_expr = "COALESCE(NULLIF(offer_yuan, ''), NULLIF(valuation_yuan, ''))"
            order_clause = (
                f"({offer_expr}) IS NULL, CAST({offer_expr} AS REAL) {sort_dir_sql}"
            )
        else:
            order_clause = f"{sort_by} IS NULL, {sort_by} {sort_dir_sql}"

        # Build and execute main query
        query = f"""
            SELECT * FROM reports
            WHERE {where_sql}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
        """
        rows = cursor.execute(query, params + [page_size, offset]).fetchall()

        conn.close()

        # Convert rows to dicts and compute push status
        reports = []
        for row in rows:
            meta = dict(row)
            # Parse JSON fields
            if meta.get("push_records"):
                try:
                    push_records = json.loads(meta["push_records"])
                except:
                    push_records = {}
            else:
                push_records = {}

            if meta.get("attachments"):
                try:
                    meta["attachments"] = json.loads(meta["attachments"])
                except:
                    meta["attachments"] = []
            else:
                meta["attachments"] = []

            # Older reports may not have attachments JSON backfilled yet.
            # Fallback to attachment directory so homepage count is accurate.
            if not meta["attachments"]:
                meta["attachments"] = _collect_attachments(meta["report_id"])

            # Compute push status
            report_id = meta["report_id"]
            status_val, info = _compute_push_status(report_id, push_records, dataset_id)
            meta["push_status"] = status_val
            meta["push_info"] = info
            meta["push_records"] = push_records
            reports.append(meta)

        return {
            "reports": reports,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

    except Exception as e:
        log.warning(f"Failed to load reports from database: {e}, falling back to JSON files")

    # Fallback to JSON files (without pagination for backward compatibility)
    reports = []
    for md_file in OUTPUT_DIR.glob("*.md"):
        report_id = md_file.stem
        meta = _load_report_meta(report_id)
        if meta:
            # Ownership filtering
            report_owner = meta.get("owner")
            if user["role"] != "admin":
                # Normal users can only see their own reports
                if report_owner != user["username"]:
                    continue
            else:
                # Admin can filter by owner
                if owner and report_owner != owner:
                    continue
            push_records = meta.get("push_records", {})
            status_val, info = _compute_push_status(report_id, push_records, dataset_id)
            meta["push_status"] = status_val
            meta["push_info"] = info
            reports.append(meta)
    # Sort by created_at descending (newest first)
    reports.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    total = len(reports)
    return {
        "reports": reports,
        "total": total,
        "page": 1,
        "page_size": total,
        "total_pages": 1
    }


@router.get("/progress/{task_id}")
async def progress_stream(task_id: str):
    """SSE stream for real-time pipeline progress."""
    queue = sse_manager.subscribe(task_id)

    async def event_generator():
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=300)
                yield msg
        except asyncio.TimeoutError:
            yield {"event": "timeout", "data": "{}"}
        finally:
            sse_manager.unsubscribe(task_id, queue)

    return EventSourceResponse(event_generator())


def _check_report_access(report_id: str, user: dict):
    """Check if user can access this report. Returns meta or raises 403/404."""
    meta = _load_report_meta(report_id)
    if not meta:
        raise HTTPException(404, "Report not found")
    if user["role"] != "admin" and meta.get("owner") != user["username"]:
        raise HTTPException(403, "无权访问此报告")
    return meta


@router.delete("/{report_id}")
async def delete_report(report_id: str, user: dict = Depends(get_current_user)):
    """Delete a single report and its metadata, including FastGPT collection."""
    from db import get_db

    _check_report_access(report_id, user)

    # Delete FastGPT collection if exists
    meta = _load_report_meta(report_id)
    if meta:
        push_records = meta.get("push_records") or {}
        settings = load_settings()
        fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}

        # Delete all collections across all datasets
        for dataset_id, record in push_records.items():
            collection_id = record.get("collection_id")
            if collection_id:
                try:
                    await delete_collection(collection_id, fastgpt_cfg)
                    log.info("Deleted FastGPT collection %s for report %s", collection_id, report_id)
                except Exception as e:
                    log.warning("Failed to delete FastGPT collection %s: %s", collection_id, e)

    # Delete local files
    _delete_report_artifacts(report_id)

    # Delete from database
    try:
        conn = get_db()
        _delete_report_related_rows(conn, report_id)
        conn.commit()
        conn.close()
        log.info(f"Deleted report {report_id} from database")
    except Exception as e:
        log.error(f"Failed to delete report {report_id} from database: {e}")

    try:
        from routers.intake import cleanup_runtime_state_for_report
        cleared_task_ids = cleanup_runtime_state_for_report(report_id)
        if cleared_task_ids:
            log.info("Cleared runtime intake state for report %s: %s", report_id, cleared_task_ids)
    except Exception as e:
        log.warning("Failed to clear runtime intake state for report %s: %s", report_id, e)

    return {"deleted": report_id}


@router.post("/batch-delete")
async def batch_delete(req: BatchDeleteRequest, user: dict = Depends(get_current_user)):
    """Delete multiple reports, including their FastGPT collections."""
    from db import get_db

    deleted = []
    settings = load_settings()
    fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}

    for rid in req.report_ids:
        try:
            _check_report_access(rid, user)
        except HTTPException:
            continue

        # Delete FastGPT collections
        meta = _load_report_meta(rid)
        if meta:
            push_records = meta.get("push_records") or {}
            for dataset_id, record in push_records.items():
                collection_id = record.get("collection_id")
                if collection_id:
                    try:
                        await delete_collection(collection_id, fastgpt_cfg)
                        log.info("Deleted FastGPT collection %s for report %s", collection_id, rid)
                    except Exception as e:
                        log.warning("Failed to delete FastGPT collection %s: %s", collection_id, e)

        # Delete local files
        _delete_report_artifacts(rid)

        # Delete from database
        try:
            conn = get_db()
            _delete_report_related_rows(conn, rid)
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Failed to delete report {rid} from database: {e}")

        try:
            from routers.intake import cleanup_runtime_state_for_report
            cleared_task_ids = cleanup_runtime_state_for_report(rid)
            if cleared_task_ids:
                log.info("Cleared runtime intake state for report %s: %s", rid, cleared_task_ids)
        except Exception as e:
            log.warning("Failed to clear runtime intake state for report %s: %s", rid, e)

        deleted.append(rid)

    return {"deleted": deleted}


@router.get("/{report_id}")
async def get_report(report_id: str, user: dict = Depends(get_current_user)):
    """Return the generated report markdown."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    if report_path.exists():
        content = report_path.read_text(encoding="utf-8")
        return {"report_id": report_id, "content": content}

    built = _build_v3_markdown(report_id)
    if built:
        _, markdown = built
        meta = _load_report_meta(report_id) or {}
        return {
            "report_id": report_id,
            "content": markdown,
            "format": meta.get("report_format") or "v3",
        }

    raise HTTPException(404, "Report not found")


@router.get("/{report_id}/chunks")
async def get_chunks(report_id: str, user: dict = Depends(get_current_user)):
    """Return report chunks for a report."""
    _check_report_access(report_id, user)
    chunks = _load_v3_chunks(report_id)
    if not chunks:
        raise HTTPException(404, "Chunks not found")
    meta = _load_report_meta(report_id) or {}
    return {"chunks": chunks, "format": meta.get("report_format") or "v4"}


@router.put("/{report_id}/chunks")
async def save_chunks(report_id: str, chunks: list[ReportChunk], user: dict = Depends(get_current_user)):
    """Save edited chunks."""
    _check_report_access(report_id, user)
    data = [c.model_dump() for c in chunks]
    now = __import__("datetime").datetime.now().isoformat()
    report_meta = _load_report_meta(report_id) or {"report_id": report_id}
    from services.pipeline_v3 import _load_report_metadata_json

    raw_chunk_state: dict[str, dict[str, Any]] = {}
    for idx, chunk in enumerate(data):
        chunk_id = chunk.get("chunk_id") or ("info" if idx == 0 else f"chunk{idx}")
        raw_chunk_state[chunk_id] = {
            "summary": chunk.get("summary", ""),
            "content": chunk.get("content") or chunk.get("q", ""),
            "index_tags": [
                item.get("text", "")
                for item in (chunk.get("indexes") or [])
                if item.get("text", "").strip()
            ],
        }

    existing_metadata = _load_report_metadata_json(report_id)
    normalized_chunks, metadata_updates, field_updates, markdown = _rebuild_manual_v4_state(
        report_meta,
        existing_metadata,
        raw_chunk_state,
    )
    merged_metadata = {**existing_metadata, **metadata_updates}
    next_status = "updated" if (report_meta.get("status") or "completed") == "completed" else (report_meta.get("status") or "completed")
    file_size = len(markdown.encode("utf-8"))

    conn = get_db()
    try:
        conn.execute("DELETE FROM report_chunks WHERE report_id = ?", (report_id,))
        for chunk_id, chunk_data in normalized_chunks.items():
            conn.execute(
                """INSERT OR REPLACE INTO report_chunks
                   (report_id, chunk_id, label, summary, content, index_tags, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    report_id,
                    chunk_id,
                    _ALL_CHUNK_LABELS.get(chunk_id, chunk_id),
                    chunk_data.get("summary", ""),
                    chunk_data.get("content", ""),
                    json.dumps(chunk_data.get("index_tags", []), ensure_ascii=False),
                    now,
                ),
            )
        conn.execute(
            "UPDATE reports SET updated_at = ?, report_format = ?, status = ?, "
            "metadata_json = ?, referral_status = ?, is_traded = ?, offer_yuan = ?, offer_date = ?, "
            "valuation_yuan = ?, valuation_date = ?, file_size = ? WHERE report_id = ?",
            (
                now,
                "v4",
                next_status,
                json.dumps(merged_metadata, ensure_ascii=False),
                field_updates.get("referral_status"),
                field_updates.get("is_traded"),
                field_updates.get("offer_yuan"),
                field_updates.get("offer_date"),
                field_updates.get("valuation_yuan"),
                field_updates.get("valuation_date"),
                file_size,
                report_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    paths = _get_report_paths(report_id)
    paths["md"].parent.mkdir(parents=True, exist_ok=True)
    paths["md"].write_text(markdown, encoding="utf-8")

    if paths["json"].exists():
        try:
            meta = json.loads(paths["json"].read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        meta.update({
            "report_format": "v4",
            "status": next_status,
            "updated_at": now,
            "file_size": file_size,
            "referral_status": field_updates.get("referral_status"),
            "is_traded": field_updates.get("is_traded"),
            "offer_yuan": field_updates.get("offer_yuan"),
            "offer_date": field_updates.get("offer_date"),
            "valuation_yuan": field_updates.get("valuation_yuan"),
            "valuation_date": field_updates.get("valuation_date"),
            "metadata_json": merged_metadata,
        })
        paths["json"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "ok", "count": len(data), "format": "v4"}


@router.post("/{report_id}/push-fastgpt")
async def push_to_fastgpt(report_id: str, user: dict = Depends(get_current_user)):
    """Push chunks to FastGPT knowledge base with improved naming and tags."""
    _check_report_access(report_id, user)

    # Load FastGPT config
    settings = load_settings()
    fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}

    try:
        return await push_report_to_fastgpt(report_id, fastgpt_cfg, replace_existing=True)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("FastGPT push failed for %s", report_id)
        raise HTTPException(502, f"FastGPT推送失败: {e}")


@router.get("/{report_id}/meta")
async def get_report_meta(report_id: str, user: dict = Depends(get_current_user)):
    """Get report metadata including attachments."""
    _check_report_access(report_id, user)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,)
        ).fetchone()

        if not row:
            raise HTTPException(404, "Report not found")

        # Convert row to dict
        meta = dict(row)
        meta.pop("locked_fields", None)

        # Parse attachments JSON
        if meta.get("attachments"):
            import json
            try:
                meta["attachments"] = json.loads(meta["attachments"])
            except json.JSONDecodeError:
                meta["attachments"] = []
        else:
            meta["attachments"] = []

        if not meta["attachments"]:
            meta["attachments"] = _collect_attachments(report_id)
            if meta["attachments"]:
                _sync_attachments_db(report_id, meta["attachments"])

        return meta
    finally:
        conn.close()


@router.get("/{report_id}/attachments/{filename}")
async def download_attachment(
    report_id: str,
    filename: str,
    user: dict = Depends(get_current_user)
):
    """Download a specific attachment file."""
    from fastapi.responses import FileResponse
    from utils.attachment_manager import get_attachment_path

    _check_report_access(report_id, user)

    file_path = get_attachment_path(report_id, filename)

    if not file_path.exists():
        raise HTTPException(404, "Attachment not found")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream"
    )


@router.put("/{report_id}/meta")
async def update_report_meta(report_id: str, updates: dict, user: dict = Depends(get_current_user)):
    """Update editable metadata fields."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    meta_path = paths["json"]
    editable_updates = {
        key: value
        for key, value in updates.items()
        if key not in _PROTECTED_META_KEYS
    }
    if not editable_updates:
        return {"status": "ok", "applied": 0}

    now = __import__("datetime").datetime.now().isoformat()
    report_meta = (_load_report_meta(report_id) or {}) | editable_updates
    applied = len(editable_updates)

    from services.pipeline_v3 import (
        _coerce_to_v4_chunk_state,
        _load_existing_chunks,
        _load_report_metadata_json,
    )

    existing_chunks = _coerce_to_v4_chunk_state(_load_existing_chunks(report_id) or {})
    existing_metadata = _load_report_metadata_json(report_id)
    is_v4_report = (
        (report_meta.get("report_format") == "v4")
        or ("info" in existing_chunks)
        or ("tracking" in existing_chunks)
    )

    file_size: int | None = None
    markdown: str | None = None
    normalized_chunks: dict[str, dict[str, Any]] | None = None
    metadata_updates: dict[str, Any] = {}
    derived_field_updates: dict[str, Any] = {}

    if is_v4_report and existing_chunks:
        normalized_chunks, metadata_updates, derived_field_updates, markdown = _rebuild_manual_v4_state(
            report_meta,
            existing_metadata,
            existing_chunks,
            explicit_field_overrides=editable_updates,
        )
        file_size = len(markdown.encode("utf-8"))

    conn = get_db()
    try:
        cursor = conn.cursor()

        if normalized_chunks is not None:
            cursor.execute("DELETE FROM report_chunks WHERE report_id = ?", (report_id,))
            for chunk_id, chunk_data in normalized_chunks.items():
                cursor.execute(
                    """INSERT OR REPLACE INTO report_chunks
                       (report_id, chunk_id, label, summary, content, index_tags, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        report_id,
                        chunk_id,
                        _ALL_CHUNK_LABELS.get(chunk_id, chunk_id),
                        chunk_data.get("summary", ""),
                        chunk_data.get("content", ""),
                        json.dumps(chunk_data.get("index_tags", []), ensure_ascii=False),
                        now,
                    ),
                )

        update_fields = []
        update_values = []
        for key, value in editable_updates.items():
            update_fields.append(f"{key} = ?")
            update_values.append(value)

        if normalized_chunks is not None:
            merged_metadata = {**existing_metadata, **metadata_updates}
            for key, value in {
                "report_format": "v4",
                "metadata_json": json.dumps(merged_metadata, ensure_ascii=False),
                "referral_status": derived_field_updates.get("referral_status"),
                "is_traded": derived_field_updates.get("is_traded"),
                "offer_yuan": derived_field_updates.get("offer_yuan"),
                "offer_date": derived_field_updates.get("offer_date"),
                "valuation_yuan": derived_field_updates.get("valuation_yuan"),
                "valuation_date": derived_field_updates.get("valuation_date"),
            }.items():
                if key in editable_updates:
                    continue
                update_fields.append(f"{key} = ?")
                update_values.append(value)
            if file_size is not None:
                update_fields.append("file_size = ?")
                update_values.append(file_size)

        update_fields.append("updated_at = ?")
        update_values.append(now)
        update_values.append(report_id)

        query = f"""
            UPDATE reports SET
                {', '.join(update_fields)}
            WHERE report_id = ?
        """
        cursor.execute(query, update_values)
        conn.commit()
    finally:
        conn.close()

    if markdown is not None:
        paths["md"].parent.mkdir(parents=True, exist_ok=True)
        paths["md"].write_text(markdown, encoding="utf-8")

    if meta_path.exists():
        try:
            sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            sidecar = {}
        sidecar.pop("locked_fields", None)
        sidecar.update(editable_updates)
        sidecar["updated_at"] = now
        if normalized_chunks is not None:
            sidecar.update({
                "report_format": "v4",
                "metadata_json": {**existing_metadata, **metadata_updates},
                "referral_status": derived_field_updates.get("referral_status"),
                "is_traded": derived_field_updates.get("is_traded"),
                "offer_yuan": derived_field_updates.get("offer_yuan"),
                "offer_date": derived_field_updates.get("offer_date"),
                "valuation_yuan": derived_field_updates.get("valuation_yuan"),
                "valuation_date": derived_field_updates.get("valuation_date"),
            })
            if file_size is not None:
                sidecar["file_size"] = file_size
        meta_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "ok", "applied": applied}


@router.post("/{report_id}/confirm")
async def confirm_report(report_id: str, user: dict = Depends(get_current_user)):
    """Confirm an updated report: status 'updated' → 'completed'."""
    _check_report_access(report_id, user)
    meta = _load_report_meta(report_id)
    if not meta:
        raise HTTPException(404, "Report metadata not found")
    if meta.get("status") != "updated":
        raise HTTPException(400, "报告状态不是[已更新]，无需确认")

    # Database is the source of truth. Use conditional update to avoid stale writes.
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reports SET status = ?, updated_at = ? WHERE report_id = ? AND status = ?",
            (
                "completed",
                __import__("datetime").datetime.now().isoformat(),
                report_id,
                "updated",
            ),
        )
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(400, "报告状态不是[已更新]，无需确认")
        conn.commit()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to confirm report in database for {report_id}: {e}")
        raise HTTPException(500, "确认失败：数据库更新异常")

    # Sync sidecar JSON if present.
    paths = _get_report_paths(report_id)
    meta_path = paths["json"]
    if meta_path.exists():
        try:
            file_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            file_meta["status"] = "completed"
            meta_path.write_text(json.dumps(file_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning(f"Failed to sync JSON metadata for {report_id}: {e}")

    return {"status": "ok"}


class UpdateContentRequest(BaseModel):
    content: str


@router.put("/{report_id}/content")
async def update_report_content(
    report_id: str,
    req: UpdateContentRequest,
    user: dict = Depends(get_current_user)
):
    """Reject direct markdown edits; v4 edits must go through fact chunks."""
    _ = req
    _check_report_access(report_id, user)
    raise HTTPException(
        status_code=410,
        detail="文稿预览页已下线，报告 Markdown 为派生产物；请在 Info / Tracking 中编辑事实块。",
    )


@router.get("/{report_id}/attachments")
async def list_attachments(report_id: str, user: dict = Depends(get_current_user)):
    """List attachments for a report."""
    _check_report_access(report_id, user)
    files = _collect_attachments(report_id)
    return {"attachments": files}


@router.get("/{report_id}/attachments/{filename}")
async def download_attachment(report_id: str, filename: str, user: dict = Depends(get_current_user)):
    """Download a specific attachment file."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    fp = paths["attachments"] / filename
    if not fp.exists():
        raise HTTPException(404, "Attachment not found")
    return FileResponse(path=str(fp), filename=filename)


@router.delete("/{report_id}/attachments/{filename}")
async def delete_attachment(report_id: str, filename: str, user: dict = Depends(get_current_user)):
    """Delete a specific attachment file."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    fp = paths["attachments"] / filename
    if not fp.exists():
        raise HTTPException(404, "Attachment not found")
    fp.unlink()

    # Refresh attachment metadata from disk and sync to JSON + DB.
    refreshed_attachments = _collect_attachments(report_id)

    meta_path = paths["json"]
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["attachments"] = refreshed_attachments
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    _sync_attachments_db(report_id, refreshed_attachments)

    return {"status": "ok"}


@router.post("/{report_id}/attachments")
async def upload_attachment(
    report_id: str,
    files: list[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload attachments to an existing report."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    att_dir = paths["attachments"]
    att_dir.mkdir(exist_ok=True)
    uploaded = []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in (".pdf", ".md", ".txt", ".docx", ".pptx"):
            continue
        raw = await f.read()
        if not raw:
            continue
        dest = att_dir / f.filename
        dest.write_bytes(raw)
        uploaded.append({"filename": f.filename, "size": len(raw)})

    # Refresh attachment metadata from disk and sync to JSON + DB.
    refreshed_attachments = _collect_attachments(report_id)
    meta_path = paths["json"]
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["attachments"] = refreshed_attachments
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    _sync_attachments_db(report_id, refreshed_attachments)

    return {"uploaded": len(uploaded), "files": uploaded}


@router.post("/{report_id}/attachments/update-report")
async def update_report_from_attachments(
    report_id: str,
    body: AttachmentUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Create an attachment-driven update task without external research."""
    from services.attachment_update_pipeline import run_attachment_update_pipeline
    from services.intake_log_service import write_intake_log
    from services.task_manager import TaskStatus, task_manager

    _check_report_access(report_id, user)

    normalized_filenames = []
    for name in body.attachment_filenames or []:
        safe_name = Path(name).name
        if safe_name and safe_name not in normalized_filenames:
            normalized_filenames.append(safe_name)
    if not normalized_filenames:
        raise HTTPException(400, "请选择至少一个附件参与更新")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT report_id, bd_code, company_name FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(404, "Report not found")

    paths = _get_report_paths(report_id)
    missing = [name for name in normalized_filenames if not (paths["attachments"] / name).exists()]
    if missing:
        raise HTTPException(404, f"附件不存在: {', '.join(missing)}")

    settings = load_settings()
    total_steps = 5 if (settings.get("fastgpt", {}) or {}).get("enabled") else 4
    task_id = uuid.uuid4().hex[:12]
    operator = user.get("username")
    company_name = row["company_name"] or ""
    bd_code = row["bd_code"]

    await task_manager.create_intake_task(
        task_id=task_id,
        report_id=report_id,
        owner=operator,
        company_name=company_name,
        bd_code=bd_code,
        task_kind="attachment_update",
        total_steps=total_steps,
        message="附件已上传，等待更新",
    )

    async def _persist_progress(step: int, total: int, message: str) -> None:
        current_step = max(0, min(step, total_steps))
        await task_manager.update_task_status(
            task_id,
            TaskStatus.RUNNING,
            current_step=current_step,
            message=message,
        )

    async def _run():
        try:
            result = await run_attachment_update_pipeline(
                report_id=report_id,
                attachment_filenames=normalized_filenames,
                settings=settings,
                owner=operator,
                user_note=body.note,
                on_progress=_persist_progress,
            )

            await task_manager.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                current_step=total_steps,
                message="附件更新完成",
            )

            steps_executed = ["AttachmentUpdatePlanner"]
            if result.get("updated_chunks"):
                steps_executed.extend(["ChunkWriter", "RatingAgent"])
            auto_push = result.get("auto_push", {}) or {}
            if auto_push.get("status") in {"pushed", "skipped"}:
                steps_executed.append("FastGPTPush")

            trigger_reason = "首页附件上传后触发更新（不联网调研）"
            if body.note and body.note.strip():
                trigger_reason += f"；备注：{body.note.strip()}"

            write_intake_log(
                report_id=report_id,
                log_type="attachment_update",
                trigger_reason=trigger_reason,
                input_sources=result.get("attachments_used", normalized_filenames),
                changed_fields=result.get("backfilled_fields") or _build_attachment_update_log_fields(
                    result.get("updated_chunks", []),
                    result.get("attachments_used", normalized_filenames),
                ),
                steps_executed=steps_executed,
                steps_skipped=result.get("steps_skipped", []),
                research_data_age_days=None,
                operator=operator,
            )
        except Exception as e:
            log.exception("Attachment-driven report update failed for %s", report_id)
            await task_manager.update_task_status(
                task_id,
                TaskStatus.FAILED,
                current_step=0,
                message=f"附件更新失败: {e}",
                error_message=str(e),
            )

    asyncio.create_task(_run())

    return {
        "task_id": task_id,
        "report_id": report_id,
        "bd_code": bd_code,
        "type": "attachment_update",
        "pipeline": "attachment_update",
        "auto_push_enabled": total_steps >= 5,
    }


@router.get("/{report_id}/download")
async def download_report(report_id: str):
    """Download the report as a .md file."""
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    md_text = ""
    company_name = report_id

    if report_path.exists():
        md_text = report_path.read_text(encoding="utf-8")
        meta_path = paths["json"]
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                company_name = meta.get("company_name") or company_name
            except Exception:
                pass
    else:
        built = _build_v3_markdown(report_id)
        if not built:
            raise HTTPException(404, "Report not found")
        company_name, md_text = built

    filename = f"尽调报告_{company_name}.md"
    encoded_filename = quote(filename)
    return Response(
        content=md_text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.get("/{report_id}/download/pdf")
async def download_report_pdf(report_id: str):
    """Download the report as a PDF file (converted from markdown)."""
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    md_text = ""
    company_name = report_id

    if report_path.exists():
        md_text = report_path.read_text(encoding="utf-8")
        meta_path = paths["json"]
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                company_name = meta.get("company_name") or company_name
            except Exception:
                pass
    else:
        built = _build_v3_markdown(report_id)
        if not built:
            raise HTTPException(404, "Report not found")
        company_name, md_text = built

    filename = f"尽调报告_{company_name}.pdf"

    pdf_path = paths["md"].parent / f"{report_id}.pdf"
    _md_to_pdf(md_text, pdf_path)

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )


def _md_to_pdf(md_text: str, out_path: Path) -> None:
    """Convert markdown text to PDF using pymupdf Story API."""
    import fitz  # pymupdf

    # Simple markdown → HTML conversion (no extra dependency)
    html_body = _simple_md_to_html(md_text)
    full_html = (
        '<html><head><style>'
        'body { font-family: "Microsoft YaHei", "SimSun", "Noto Sans SC", sans-serif; '
        'font-size: 10.5pt; line-height: 1.6; color: #222; } '
        'h1 { font-size: 18pt; margin-top: 12pt; } '
        'h2 { font-size: 15pt; margin-top: 10pt; } '
        'h3 { font-size: 13pt; margin-top: 8pt; } '
        'h4 { font-size: 11pt; margin-top: 6pt; } '
        'table { border-collapse: collapse; width: 100%; margin: 8pt 0; } '
        'th, td { border: 1px solid #999; padding: 4pt 6pt; font-size: 9pt; } '
        'th { background: #f0f0f0; font-weight: bold; } '
        'code { font-family: monospace; background: #f5f5f5; padding: 1pt 3pt; font-size: 9pt; } '
        'pre { background: #f5f5f5; padding: 8pt; font-size: 9pt; } '
        'ul, ol { padding-left: 20pt; } '
        'li { margin-bottom: 2pt; } '
        'hr { border: none; border-top: 1px solid #ccc; margin: 10pt 0; } '
        '</style></head><body>' + html_body + '</body></html>'
    )

    story = fitz.Story(html=full_html)
    writer = fitz.DocumentWriter(str(out_path))
    mediabox = fitz.paper_rect("a4")
    # 72pt margins (1 inch)
    where = mediabox + fitz.Rect(54, 54, -54, -54)

    while True:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
        if not more:
            break

    writer.close()


def _simple_md_to_html(md: str) -> str:
    """Minimal markdown to HTML converter (no external dependency)."""
    import html as html_mod

    lines = md.split("\n")
    out: list[str] = []
    in_code = False
    in_table = False
    in_list = False
    list_type = ""

    for line in lines:
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(html_mod.escape(line))
            continue

        stripped = line.strip()

        # Empty line
        if not stripped:
            if in_list:
                out.append(f"</{list_type}>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            out.append("")
            continue

        # Table rows
        if "|" in stripped and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Skip separator rows like |---|---|
            if all(c.replace("-", "").replace(":", "") == "" for c in cells):
                continue
            if not in_table:
                out.append("<table><tr>")
                for c in cells:
                    out.append(f"<th>{_inline(c)}</th>")
                out.append("</tr>")
                in_table = True
            else:
                out.append("<tr>")
                for c in cells:
                    out.append(f"<td>{_inline(c)}</td>")
                out.append("</tr>")
            continue

        if in_table:
            out.append("</table>")
            in_table = False

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}$", stripped):
            out.append("<hr/>")
            continue

        # Unordered list
        m = re.match(r"^[-*+]\s+(.*)", stripped)
        if m:
            if not in_list or list_type != "ul":
                if in_list:
                    out.append(f"</{list_type}>")
                out.append("<ul>")
                in_list = True
                list_type = "ul"
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Ordered list
        m = re.match(r"^\d+\.\s+(.*)", stripped)
        if m:
            if not in_list or list_type != "ol":
                if in_list:
                    out.append(f"</{list_type}>")
                out.append("<ol>")
                in_list = True
                list_type = "ol"
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        if in_list:
            out.append(f"</{list_type}>")
            in_list = False

        # Paragraph
        out.append(f"<p>{_inline(stripped)}</p>")

    if in_code:
        out.append("</code></pre>")
    if in_list:
        out.append(f"</{list_type}>")
    if in_table:
        out.append("</table>")

    return "\n".join(out)


def _inline(text: str) -> str:
    """Handle inline markdown: bold, italic, code, links."""
    # Code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


# ── Rating Management ─────────────────────────────────────────────

@router.post("/{report_id}/rating-confirm")
async def confirm_rating_change(
    report_id: str,
    body: dict,
    user: dict = Depends(get_current_user)
):
    """Confirm or reject a pending rating change.

    Body:
        {
            "action": "accept" | "reject",
            "note": "optional user note"
        }
    """
    _check_report_access(report_id, user)

    action = body.get("action")
    note = body.get("note", "")

    if action not in ("accept", "reject"):
        raise HTTPException(400, "action must be 'accept' or 'reject'")

    conn = get_db()
    try:
        # Get current pending change
        row = conn.execute(
            "SELECT pending_rating_change FROM reports WHERE report_id = ?",
            (report_id,)
        ).fetchone()

        if not row:
            raise HTTPException(404, "Report not found")

        pending_json = row["pending_rating_change"]
        if not pending_json:
            raise HTTPException(400, "No pending rating change")

        import json
        pending = json.loads(pending_json)

        if action == "accept":
            # Apply the new rating
            conn.execute(
                """
                UPDATE reports
                SET feasibility_rating = ?,
                    feasibility_rating_detail = ?,
                    feasibility_rating_at = datetime('now','localtime'),
                    pending_rating_change = NULL
                WHERE report_id = ?
                """,
                (
                    pending["rating"],
                    json.dumps(pending, ensure_ascii=False),
                    report_id,
                )
            )
            conn.commit()
            return {"status": "accepted", "new_rating": pending["rating"]}

        else:  # reject
            # Clear pending change, keep old rating
            conn.execute(
                "UPDATE reports SET pending_rating_change = NULL WHERE report_id = ?",
                (report_id,)
            )
            conn.commit()
            return {"status": "rejected"}

    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Failed to confirm rating change for {report_id}")
        raise HTTPException(500, f"操作失败: {e}")
    finally:
        conn.close()


@router.get("/{report_id}/chunks-legacy")
@router.get("/{report_id}/chunks-v3")
async def get_legacy_chunks(report_id: str, user: dict = Depends(get_current_user)):
    """Get legacy chunk data from `report_chunks` for compatibility tooling."""
    _check_report_access(report_id, user)

    from utils.fastgpt_adapter import load_chunks_v3

    try:
        chunks = load_chunks_v3(report_id)
        return {"chunks": chunks, "format": "v3"}
    except Exception as e:
        log.exception(f"Failed to load legacy chunks for {report_id}")
        raise HTTPException(500, f"加载失败: {e}")

