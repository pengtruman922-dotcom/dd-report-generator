"""Report generation, progress SSE, list, delete, and download endpoints."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import logging

from auth import get_current_user
from config import OUTPUT_DIR, load_settings, DEFAULT_FASTGPT_CONFIG
from parsers.pdf_parser import extract_pdf_text
from services.chunker import chunk_and_index
from services.fastgpt_uploader import (
    push_chunks_to_fastgpt,
    delete_collection,
    save_push_record,
    compute_chunks_hash,
)

log = logging.getLogger(__name__)
from parsers.md_parser import read_md
from parsers.docx_parser import extract_docx_text
from parsers.pptx_parser import extract_pptx_text
from services.pipeline import run_pipeline
from services.sse_manager import sse_manager
from services.task_manager import task_manager
from routers.upload import get_session as get_upload_session

router = APIRouter()


class GenerateRequest(BaseModel):
    session_id: str
    bd_code: str
    report_id: str | None = None  # For regeneration: overwrite existing report


class BatchGenerateRequest(BaseModel):
    session_id: str
    bd_codes: list[str]


class BatchDeleteRequest(BaseModel):
    report_ids: list[str]


class ChunkIndex(BaseModel):
    text: str


class ReportChunk(BaseModel):
    title: str
    q: str
    indexes: list[ChunkIndex] = []


def _parse_attachment_file(fp: Path) -> str:
    """Parse text from an attachment file on disk."""
    ext = fp.suffix.lower()
    if ext == ".pdf":
        return extract_pdf_text(fp)
    if ext in (".md", ".txt"):
        return read_md(fp)
    if ext == ".docx":
        return extract_docx_text(fp)
    if ext == ".pptx":
        return extract_pptx_text(fp)
    return ""


# Protected system fields that cannot be edited
_PROTECTED_META_KEYS = {
    "report_id", "bd_code", "status", "score", "rating",
    "created_at", "file_size", "owner", "push_records",
    "push_status", "push_info", "attachments",
}


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
                "chunks": Path(row["chunks_path"]) if row["chunks_path"] else OUTPUT_DIR / f"{report_id}_chunks.json",
                "debug": Path(row["debug_dir"]) if row["debug_dir"] else OUTPUT_DIR / f"{report_id}_debug",
                "attachments": Path(row["attachments_dir"]) if row["attachments_dir"] else OUTPUT_DIR / f"{report_id}_attachments",
            }
    except Exception as e:
        log.warning(f"Failed to get paths from database for {report_id}: {e}")

    # Fallback to default paths
    return {
        "md": OUTPUT_DIR / f"{report_id}.md",
        "json": OUTPUT_DIR / f"{report_id}.json",
        "chunks": OUTPUT_DIR / f"{report_id}_chunks.json",
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
            # Parse JSON fields
            if meta.get("locked_fields"):
                try:
                    meta["locked_fields"] = json.loads(meta["locked_fields"])
                except:
                    meta["locked_fields"] = []
            if meta.get("push_records"):
                try:
                    meta["push_records"] = json.loads(meta["push_records"])
                except:
                    meta["push_records"] = {}
            if meta.get("attachments"):
                try:
                    meta["attachments"] = json.loads(meta["attachments"])
                except:
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
            return json.loads(meta_path.read_text(encoding="utf-8"))
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


def _compute_push_status(
    report_id: str,
    push_records: dict,
    dataset_id: str,
) -> tuple[str, dict | None]:
    """Compute push status relative to the current dataset_id.

    Returns (status, push_info) where status is one of:
      no_chunks, not_pushed, pushed, outdated
    """
    paths = _get_report_paths(report_id)
    chunks_path = paths["chunks"]
    if not chunks_path.exists():
        return "no_chunks", None
    if not dataset_id or dataset_id not in push_records:
        return "not_pushed", None
    record = push_records[dataset_id]
    try:
        current_hash = compute_chunks_hash(report_id)
    except Exception:
        return "not_pushed", None
    if record.get("chunks_hash") == current_hash:
        return "pushed", record
    return "outdated", record


@router.get("/list")
async def list_reports(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, description="Search in company_name, bd_code"),
    status: str | None = Query(None, description="Filter by status"),
    rating: str | None = Query(None, description="Filter by rating"),
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

        # Search filter
        if search:
            where_clauses.append("(company_name LIKE ? OR bd_code LIKE ?)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])

        # Build WHERE clause string
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Get total count
        count_query = f"SELECT COUNT(*) FROM reports WHERE {where_sql}"
        total = cursor.execute(count_query, params).fetchone()[0]

        # Calculate pagination
        offset = (page - 1) * page_size
        total_pages = (total + page_size - 1) // page_size

        # Validate sort_by field (prevent SQL injection)
        allowed_sort_fields = {
            "created_at", "updated_at", "company_name", "bd_code",
            "score", "rating", "status", "province", "industry"
        }
        if sort_by not in allowed_sort_fields:
            sort_by = "created_at"

        # Build and execute main query
        query = f"""
            SELECT * FROM reports
            WHERE {where_sql}
            ORDER BY {sort_by} {sort_dir.upper()}
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


@router.post("/generate")
async def generate_report(req: GenerateRequest, user: dict = Depends(get_current_user)):
    """Start report generation; returns task_id for SSE progress."""
    try:
        session = get_upload_session(req.session_id)
    except HTTPException:
        raise HTTPException(404, "Session not found")

    # Find the Excel row
    excel_row = None
    for row in session["all_rows"]:
        if str(row.get("bd_code", "")) == req.bd_code:
            excel_row = row
            break
    if not excel_row:
        raise HTTPException(404, f"Company {req.bd_code} not found in Excel")

    # Collect attachment texts with filenames
    # Primary: use pre-parsed texts from upload (parsed from in-memory bytes,
    # avoids TSD filesystem encryption corrupting files on disk)
    attachment_items: list[tuple[str, str]] = []  # (filename, text)
    failed_attachments: list[str] = []

    pre_parsed = session.get("parsed_texts", {}).get(req.bd_code, [])
    if pre_parsed:
        log.info("Using %d pre-parsed attachment(s) for bd_code=%s", len(pre_parsed), req.bd_code)
        for filename, text in pre_parsed:
            if text and text.strip():
                attachment_items.append((filename, text))
                log.info("Pre-parsed attachment: %s → %d chars", filename, len(text))
            else:
                log.warning("Pre-parsed attachment empty: %s", filename)
                failed_attachments.append(f"{filename} (解析结果为空)")
    else:
        # Fallback: parse from disk (for sessions created before in-memory parsing)
        all_attachment_paths = session.get("attachments", {}).get(req.bd_code, [])
        log.info("No pre-parsed texts, falling back to disk parsing for %d file(s), bd_code=%s",
                 len(all_attachment_paths), req.bd_code)

        for fpath in all_attachment_paths:
            p = Path(fpath)
            try:
                if not p.exists():
                    log.warning("Attachment file not found: %s", fpath)
                    failed_attachments.append(f"{p.name} (文件不存在)")
                    continue
                file_size = p.stat().st_size
                if file_size == 0:
                    log.warning("Attachment file is empty (0 bytes): %s", fpath)
                    failed_attachments.append(f"{p.name} (文件为空)")
                    continue

                log.info("Parsing attachment from disk: %s (%d bytes)", p.name, file_size)
                text = ""
                if p.suffix.lower() == ".pdf":
                    text = extract_pdf_text(p)
                elif p.suffix.lower() in (".md", ".txt"):
                    text = read_md(p)
                elif p.suffix.lower() == ".docx":
                    text = extract_docx_text(p)
                elif p.suffix.lower() == ".pptx":
                    text = extract_pptx_text(p)

                if text:
                    attachment_items.append((p.name, text))
                    log.info("Successfully parsed attachment: %s → %d chars", p.name, len(text))
                else:
                    log.warning("Attachment parsed but returned empty text: %s", p.name)
                    failed_attachments.append(f"{p.name} (解析结果为空)")
            except Exception as e:
                log.exception("Failed to parse attachment: %s", fpath)
                failed_attachments.append(f"{p.name} ({e})")

    # Determine report_id: reuse for regeneration, or create new
    is_regeneration = False
    if req.report_id:
        report_id = req.report_id
        paths = _get_report_paths(report_id)
        is_regeneration = paths["md"].exists()
        # Include existing attachments from the report's attachment dir
        att_dir = paths["attachments"]
        if att_dir.exists():
            session_filenames = {name for name, _ in attachment_items}
            for fp in sorted(att_dir.iterdir()):
                if not fp.is_file() or fp.name in session_filenames:
                    continue
                try:
                    text = _parse_attachment_file(fp)
                    if text and text.strip():
                        attachment_items.append((fp.name, text))
                        log.info("Existing attachment: %s → %d chars", fp.name, len(text))
                except Exception as e:
                    log.warning("Failed to parse existing attachment %s: %s", fp.name, e)
    else:
        report_id = uuid.uuid4().hex[:12]

    task_id = report_id  # Use report_id as task_id for SSE

    # Copy session attachment files to report attachment dir
    paths = _get_report_paths(report_id)
    att_dir = paths["attachments"]
    att_dir.mkdir(exist_ok=True)
    session_file_paths = session.get("attachments", {}).get(req.bd_code, [])
    for fpath in session_file_paths:
        p = Path(fpath)
        if p.exists():
            dest = att_dir / p.name
            if not dest.exists():
                shutil.copy2(str(p), str(dest))

    # Build attachment info for metadata
    attachments_info = []
    if att_dir.exists():
        for fp in sorted(att_dir.iterdir()):
            if fp.is_file():
                attachments_info.append({"filename": fp.name, "size": fp.stat().st_size})

    log.info(
        "Generate report: bd_code=%s, report_id=%s, regen=%s, parsed=%d, failed=%d",
        req.bd_code, report_id, is_regeneration,
        len(attachment_items), len(failed_attachments),
    )
    if failed_attachments:
        log.warning("Failed attachments: %s", failed_attachments)

    # Create task record in database
    await task_manager.create_task(
        task_id=task_id,
        report_id=report_id,
        excel_row=excel_row,
        attachment_items=attachment_items,
        failed_attachments=failed_attachments,
        owner=user["username"],
        attachments_info=attachments_info,
        is_regeneration=is_regeneration,
    )

    # Launch pipeline in background with task manager
    async def pipeline_task():
        await run_pipeline(
            task_id, excel_row, attachment_items, failed_attachments,
            owner=user["username"], attachments_info=attachments_info,
            is_regeneration=is_regeneration,
        )

    await task_manager.start_task(task_id, pipeline_task)

    return {"task_id": task_id}


@router.post("/batch-generate")
async def batch_generate_reports(req: BatchGenerateRequest, user: dict = Depends(get_current_user)):
    """Start batch report generation; returns list of task_ids for SSE progress tracking."""
    try:
        session = get_upload_session(req.session_id)
    except HTTPException:
        raise HTTPException(404, "Session not found")

    task_ids = []

    for bd_code in req.bd_codes:
        # Find the Excel row
        excel_row = None
        for row in session["all_rows"]:
            if str(row.get("bd_code", "")) == bd_code:
                excel_row = row
                break
        if not excel_row:
            log.warning(f"Company {bd_code} not found in Excel, skipping")
            continue

        # Collect attachment texts
        attachment_items: list[tuple[str, str]] = []
        failed_attachments: list[str] = []

        pre_parsed = session.get("parsed_texts", {}).get(bd_code, [])
        if pre_parsed:
            for filename, text in pre_parsed:
                if text and text.strip():
                    attachment_items.append((filename, text))
                else:
                    failed_attachments.append(f"{filename} (解析结果为空)")
        else:
            all_attachment_paths = session.get("attachments", {}).get(bd_code, [])
            for fpath in all_attachment_paths:
                p = Path(fpath)
                try:
                    if not p.exists():
                        failed_attachments.append(f"{p.name} (文件不存在)")
                        continue
                    text = _parse_attachment_file(p)
                    if text:
                        attachment_items.append((p.name, text))
                    else:
                        failed_attachments.append(f"{p.name} (解析结果为空)")
                except Exception as e:
                    failed_attachments.append(f"{p.name} ({e})")

        # Create new report
        report_id = uuid.uuid4().hex[:12]
        task_id = report_id

        # Copy attachments
        paths = _get_report_paths(report_id)
        att_dir = paths["attachments"]
        att_dir.mkdir(exist_ok=True)
        session_file_paths = session.get("attachments", {}).get(bd_code, [])
        for fpath in session_file_paths:
            p = Path(fpath)
            if p.exists():
                dest = att_dir / p.name
                if not dest.exists():
                    shutil.copy2(str(p), str(dest))

        # Build attachment info
        attachments_info = []
        if att_dir.exists():
            for fp in sorted(att_dir.iterdir()):
                if fp.is_file():
                    attachments_info.append({"filename": fp.name, "size": fp.stat().st_size})

        log.info(
            "Batch generate: bd_code=%s, report_id=%s, parsed=%d, failed=%d",
            bd_code, report_id, len(attachment_items), len(failed_attachments),
        )

        # Create task record
        await task_manager.create_task(
            task_id=task_id,
            report_id=report_id,
            excel_row=excel_row,
            attachment_items=attachment_items,
            failed_attachments=failed_attachments,
            owner=user["username"],
            attachments_info=attachments_info,
            is_regeneration=False,
        )

        # Launch pipeline in background
        async def pipeline_task():
            await run_pipeline(
                task_id, excel_row, attachment_items, failed_attachments,
                owner=user["username"], attachments_info=attachments_info,
                is_regeneration=False,
            )

        await task_manager.start_task(task_id, pipeline_task)
        task_ids.append(task_id)

    return {"task_ids": task_ids, "count": len(task_ids)}


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

    paths = _get_report_paths(report_id)
    md_path = paths["md"]
    meta_path = paths["json"]
    chunks_path = paths["chunks"]
    att_dir = paths["attachments"]

    if not md_path.exists():
        raise HTTPException(404, "Report not found")

    _check_report_access(report_id, user)

    # Delete FastGPT collection if exists
    meta = _load_report_meta(report_id)
    if meta:
        push_records = meta.get("push_records", {})
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
    md_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    chunks_path.unlink(missing_ok=True)

    # Delete attachment directory
    if att_dir.exists():
        import shutil
        shutil.rmtree(att_dir, ignore_errors=True)

    # Delete from database
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
        conn.commit()
        conn.close()
        log.info(f"Deleted report {report_id} from database")
    except Exception as e:
        log.error(f"Failed to delete report {report_id} from database: {e}")

    return {"deleted": report_id}


@router.post("/batch-delete")
async def batch_delete(req: BatchDeleteRequest, user: dict = Depends(get_current_user)):
    """Delete multiple reports, including their FastGPT collections."""
    from db import get_db

    deleted = []
    settings = load_settings()
    fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}

    for rid in req.report_ids:
        paths = _get_report_paths(rid)
        md_path = paths["md"]
        meta_path = paths["json"]
        chunks_path = paths["chunks"]
        att_dir = paths["attachments"]

        if md_path.exists():
            try:
                _check_report_access(rid, user)
            except HTTPException:
                continue

            # Delete FastGPT collections
            meta = _load_report_meta(rid)
            if meta:
                push_records = meta.get("push_records", {})
                for dataset_id, record in push_records.items():
                    collection_id = record.get("collection_id")
                    if collection_id:
                        try:
                            await delete_collection(collection_id, fastgpt_cfg)
                            log.info("Deleted FastGPT collection %s for report %s", collection_id, rid)
                        except Exception as e:
                            log.warning("Failed to delete FastGPT collection %s: %s", collection_id, e)

            # Delete local files
            md_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            chunks_path.unlink(missing_ok=True)

            # Delete attachment directory
            if att_dir.exists():
                import shutil
                shutil.rmtree(att_dir, ignore_errors=True)

            # Delete from database
            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM reports WHERE report_id = ?", (rid,))
                conn.commit()
                conn.close()
            except Exception as e:
                log.error(f"Failed to delete report {rid} from database: {e}")

            deleted.append(rid)

    return {"deleted": deleted}


@router.get("/{report_id}")
async def get_report(report_id: str, user: dict = Depends(get_current_user)):
    """Return the generated report markdown."""
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    if not report_path.exists():
        raise HTTPException(404, "Report not found")
    _check_report_access(report_id, user)
    content = report_path.read_text(encoding="utf-8")
    return {"report_id": report_id, "content": content}


@router.get("/{report_id}/chunks")
async def get_chunks(report_id: str, user: dict = Depends(get_current_user)):
    """Return the chunks JSON for a report."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    chunks_path = paths["chunks"]
    if not chunks_path.exists():
        raise HTTPException(404, "Chunks not found")
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    return {"chunks": chunks}


@router.put("/{report_id}/chunks")
async def save_chunks(report_id: str, chunks: list[ReportChunk], user: dict = Depends(get_current_user)):
    """Save edited chunks JSON."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    chunks_path = paths["chunks"]
    data = [c.model_dump() for c in chunks]
    chunks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "count": len(data)}


@router.post("/{report_id}/regenerate-chunks")
async def regenerate_chunks(report_id: str, user: dict = Depends(get_current_user)):
    """Re-run chunking + AI indexing for an existing report."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    meta_path = paths["json"]
    if not report_path.exists():
        raise HTTPException(404, "Report not found")
    report_md = report_path.read_text(encoding="utf-8")
    metadata = {}
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    settings = load_settings()
    ai = settings.get("ai_config", {})
    chk_cfg = ai.get("chunker", {})
    # Fallback to extractor key if chunker has no API key
    if not chk_cfg.get("api_key"):
        fallback = ai.get("extractor", {})
        chk_cfg = {**chk_cfg, "api_key": fallback.get("api_key", ""),
                    "base_url": chk_cfg.get("base_url") or fallback.get("base_url", ""),
                    "model": chk_cfg.get("model") or fallback.get("model", "")}
    chunks = await chunk_and_index(report_md, metadata, chk_cfg)
    chunks_path = paths["chunks"]
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"chunks": chunks, "count": len(chunks)}


@router.post("/{report_id}/push-fastgpt")
async def push_to_fastgpt(report_id: str, user: dict = Depends(get_current_user)):
    """Push chunks to FastGPT knowledge base with improved naming and tags."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    chunks_path = paths["chunks"]
    if not chunks_path.exists():
        raise HTTPException(404, "Chunks not found — generate chunks first")
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

    # Load metadata
    meta_path = paths["json"]
    company_name = "未知公司"
    bd_code = report_id[:8]
    push_records: dict = {}
    manual_rating = None
    rating = None

    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        company_name = meta.get("company_name", company_name)
        bd_code = meta.get("bd_code", bd_code)
        push_records = meta.get("push_records", {})
        manual_rating = meta.get("manual_rating")
        rating = meta.get("rating")

    # Calculate final rating
    final_rating = manual_rating or rating

    # Load FastGPT config
    settings = load_settings()
    fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}
    if not fastgpt_cfg.get("api_key"):
        raise HTTPException(400, "FastGPT API Key 未配置，请在设置页面配置")
    dataset_id = fastgpt_cfg.get("dataset_id", "")

    # Delete old collection if exists for this dataset
    old_record = push_records.get(dataset_id)
    if old_record and old_record.get("collection_id"):
        await delete_collection(old_record["collection_id"], fastgpt_cfg)

    # Build collection name and tags
    collection_name = f"{company_name}-{bd_code}"
    tags = ["尽调报告", bd_code]
    if final_rating:
        tags.append(final_rating)

    try:
        result = await push_chunks_to_fastgpt(chunks, collection_name, fastgpt_cfg, tags=tags)
        # Save push record
        save_push_record(report_id, dataset_id, result["collection_id"], result["uploaded"], result["total"])
        # Return result with push_record info
        result["push_record"] = {
            "dataset_id": dataset_id,
            "collection_id": result["collection_id"],
            "uploaded": result["uploaded"],
            "total": result["total"],
        }
        return result
    except Exception as e:
        log.exception("FastGPT push failed for %s", report_id)
        raise HTTPException(502, f"FastGPT推送失败: {e}")


@router.put("/{report_id}/meta")
async def update_report_meta(report_id: str, updates: dict, user: dict = Depends(get_current_user)):
    """Update editable metadata fields. Auto-locks edited fields to prevent backfill overwrite."""
    from db import get_db

    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    meta_path = paths["json"]
    if not meta_path.exists():
        raise HTTPException(404, "Report metadata not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # Track locked fields (user-edited fields won't be overwritten by backfill)
    locked_fields = set(meta.get("locked_fields", []))

    applied = 0
    for k, v in updates.items():
        if k not in _PROTECTED_META_KEYS:
            meta[k] = v
            locked_fields.add(k)  # Mark as locked
            applied += 1

    meta["locked_fields"] = list(locked_fields)

    # Write to JSON file
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write to database
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Build update query dynamically for updated fields
        update_fields = []
        update_values = []
        for k, v in updates.items():
            if k not in _PROTECTED_META_KEYS:
                update_fields.append(f"{k} = ?")
                update_values.append(v)

        if update_fields:
            update_values.append(json.dumps(list(locked_fields)))
            update_values.append(__import__("datetime").datetime.now().isoformat())
            update_values.append(report_id)

            query = f"""
                UPDATE reports SET
                    {', '.join(update_fields)},
                    locked_fields = ?,
                    updated_at = ?
                WHERE report_id = ?
            """
            cursor.execute(query, update_values)
            conn.commit()

        conn.close()
    except Exception as e:
        log.error(f"Failed to update database for {report_id}: {e}")

    return {"status": "ok", "applied": applied}


@router.post("/{report_id}/confirm")
async def confirm_report(report_id: str, user: dict = Depends(get_current_user)):
    """Confirm an updated report: status 'updated' → 'completed'."""
    from db import get_db

    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    meta_path = paths["json"]
    if not meta_path.exists():
        raise HTTPException(404, "Report metadata not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("status") != "updated":
        raise HTTPException(400, "报告状态不是[已更新]，无需确认")
    meta["status"] = "completed"

    # Write to JSON file
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write to database
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reports SET status = ?, updated_at = ? WHERE report_id = ?",
            ("completed", __import__("datetime").datetime.now().isoformat(), report_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Failed to update database for {report_id}: {e}")

    return {"status": "ok"}


class UpdateContentRequest(BaseModel):
    content: str


@router.put("/{report_id}/content")
async def update_report_content(
    report_id: str,
    req: UpdateContentRequest,
    user: dict = Depends(get_current_user)
):
    """Update report markdown content."""
    from db import get_db

    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    if not report_path.exists():
        raise HTTPException(404, "Report not found")

    # Write updated content
    report_path.write_text(req.content, encoding="utf-8")

    # Update file_size and status in metadata
    meta_path = paths["json"]
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["file_size"] = report_path.stat().st_size
        if meta.get("status") == "completed":
            meta["status"] = "updated"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # Update database
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reports SET file_size = ?, status = ?, updated_at = ? WHERE report_id = ?",
                (meta["file_size"], meta.get("status", "completed"),
                 __import__("datetime").datetime.now().isoformat(), report_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Failed to update database for {report_id}: {e}")

    return {"status": "ok", "file_size": report_path.stat().st_size}


@router.get("/{report_id}/attachments")
async def list_attachments(report_id: str, user: dict = Depends(get_current_user)):
    """List attachments for a report."""
    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    att_dir = paths["attachments"]
    files = []
    if att_dir.exists():
        for fp in sorted(att_dir.iterdir()):
            if fp.is_file():
                files.append({"filename": fp.name, "size": fp.stat().st_size})
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
    from db import get_db

    _check_report_access(report_id, user)
    paths = _get_report_paths(report_id)
    fp = paths["attachments"] / filename
    if not fp.exists():
        raise HTTPException(404, "Attachment not found")
    fp.unlink()
    # Update metadata
    meta_path = paths["json"]
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        atts = meta.get("attachments", [])
        meta["attachments"] = [a for a in atts if a.get("filename") != filename]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # Update database
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reports SET attachments = ?, updated_at = ? WHERE report_id = ?",
                (json.dumps(meta["attachments"]), __import__("datetime").datetime.now().isoformat(), report_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Failed to update database for {report_id}: {e}")

    return {"status": "ok"}


@router.post("/{report_id}/attachments")
async def upload_attachment(
    report_id: str,
    files: list[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload attachments to an existing report."""
    from db import get_db

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
    # Update metadata
    meta_path = paths["json"]
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        existing = {a["filename"] for a in meta.get("attachments", [])}
        atts = meta.get("attachments", [])
        for u in uploaded:
            if u["filename"] not in existing:
                atts.append(u)
            else:
                atts = [a if a["filename"] != u["filename"] else u for a in atts]
        meta["attachments"] = atts
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # Update database
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reports SET attachments = ?, updated_at = ? WHERE report_id = ?",
                (json.dumps(atts), __import__("datetime").datetime.now().isoformat(), report_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Failed to update database for {report_id}: {e}")

    return {"uploaded": len(uploaded), "files": uploaded}


@router.get("/{report_id}/download")
async def download_report(report_id: str):
    """Download the report as a .md file."""
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    if not report_path.exists():
        raise HTTPException(404, "Report not found")
    # Try to get company name for filename
    meta_path = paths["json"]
    filename = f"尽调报告_{report_id}.md"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = meta.get("company_name", "")
            if name:
                filename = f"尽调报告_{name}.md"
        except Exception:
            pass
    return FileResponse(
        path=str(report_path),
        media_type="text/markdown",
        filename=filename,
    )


@router.get("/{report_id}/download/pdf")
async def download_report_pdf(report_id: str):
    """Download the report as a PDF file (converted from markdown)."""
    paths = _get_report_paths(report_id)
    report_path = paths["md"]
    if not report_path.exists():
        raise HTTPException(404, "Report not found")

    md_text = report_path.read_text(encoding="utf-8")

    # Try to get company name for filename
    meta_path = paths["json"]
    filename = f"尽调报告_{report_id}.pdf"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = meta.get("company_name", "")
            if name:
                filename = f"尽调报告_{name}.pdf"
        except Exception:
            pass

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


# ── Version Management ────────────────────────────────────────────

@router.get("/{report_id}/versions")
async def list_report_versions(report_id: str, user: dict = Depends(get_current_user)):
    """List all versions for a report."""
    _check_report_access(report_id, user)
    from services.version_manager import list_versions
    versions = list_versions(report_id)
    return {"versions": versions, "count": len(versions)}


@router.get("/{report_id}/versions/{version_id}")
async def get_report_version(
    report_id: str,
    version_id: str,
    user: dict = Depends(get_current_user)
):
    """Get a specific version content."""
    _check_report_access(report_id, user)
    from services.version_manager import get_version
    version = get_version(version_id)
    if not version or version["report_id"] != report_id:
        raise HTTPException(404, "Version not found")
    return version


@router.post("/{report_id}/versions/{version_id}/restore")
async def restore_report_version(
    report_id: str,
    version_id: str,
    user: dict = Depends(get_current_user)
):
    """Restore a report from a version."""
    _check_report_access(report_id, user)
    from services.version_manager import restore_version
    try:
        restored_id = restore_version(version_id, restored_by=user["username"])
        return {"status": "ok", "report_id": restored_id}
    except Exception as e:
        log.exception(f"Failed to restore version {version_id}")
        raise HTTPException(500, f"恢复失败: {e}")

