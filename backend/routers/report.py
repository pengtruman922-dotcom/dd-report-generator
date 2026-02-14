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
from routers.upload import get_sessions

router = APIRouter()


class GenerateRequest(BaseModel):
    session_id: str
    bd_code: str
    report_id: str | None = None  # For regeneration: overwrite existing report


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


def _load_report_meta(report_id: str) -> dict | None:
    """Load metadata for a report. Falls back to extracting from .md if no .json exists."""
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    md_path = OUTPUT_DIR / f"{report_id}.md"

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
    chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
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
async def list_reports(owner: str | None = None, user: dict = Depends(get_current_user)):
    """List reports with metadata and push status. Filtered by ownership."""
    settings = load_settings()
    fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}
    dataset_id = fastgpt_cfg.get("dataset_id", "")

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
            status, info = _compute_push_status(report_id, push_records, dataset_id)
            meta["push_status"] = status
            meta["push_info"] = info
            reports.append(meta)
    # Sort by created_at descending (newest first)
    reports.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"reports": reports, "total": len(reports)}


@router.post("/generate")
async def generate_report(req: GenerateRequest, user: dict = Depends(get_current_user)):
    """Start report generation; returns task_id for SSE progress."""
    sessions = get_sessions()
    session = sessions.get(req.session_id)
    if not session:
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
        is_regeneration = (OUTPUT_DIR / f"{report_id}.md").exists()
        # Include existing attachments from the report's attachment dir
        att_dir = OUTPUT_DIR / f"{report_id}_attachments"
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
    att_dir = OUTPUT_DIR / f"{report_id}_attachments"
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

    # Launch pipeline in background
    asyncio.create_task(run_pipeline(
        task_id, excel_row, attachment_items, failed_attachments,
        owner=user["username"], attachments_info=attachments_info,
        is_regeneration=is_regeneration,
    ))

    return {"task_id": task_id}


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
    """Delete a single report and its metadata."""
    md_path = OUTPUT_DIR / f"{report_id}.md"
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
    if not md_path.exists():
        raise HTTPException(404, "Report not found")
    _check_report_access(report_id, user)
    md_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    chunks_path.unlink(missing_ok=True)
    return {"deleted": report_id}


@router.post("/batch-delete")
async def batch_delete(req: BatchDeleteRequest, user: dict = Depends(get_current_user)):
    """Delete multiple reports."""
    deleted = []
    for rid in req.report_ids:
        md_path = OUTPUT_DIR / f"{rid}.md"
        meta_path = OUTPUT_DIR / f"{rid}.json"
        chunks_path = OUTPUT_DIR / f"{rid}_chunks.json"
        if md_path.exists():
            try:
                _check_report_access(rid, user)
            except HTTPException:
                continue
            md_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            chunks_path.unlink(missing_ok=True)
            deleted.append(rid)
    return {"deleted": deleted}


@router.get("/{report_id}")
async def get_report(report_id: str, user: dict = Depends(get_current_user)):
    """Return the generated report markdown."""
    report_path = OUTPUT_DIR / f"{report_id}.md"
    if not report_path.exists():
        raise HTTPException(404, "Report not found")
    _check_report_access(report_id, user)
    content = report_path.read_text(encoding="utf-8")
    return {"report_id": report_id, "content": content}


@router.get("/{report_id}/chunks")
async def get_chunks(report_id: str, user: dict = Depends(get_current_user)):
    """Return the chunks JSON for a report."""
    _check_report_access(report_id, user)
    chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
    if not chunks_path.exists():
        raise HTTPException(404, "Chunks not found")
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    return {"chunks": chunks}


@router.put("/{report_id}/chunks")
async def save_chunks(report_id: str, chunks: list[ReportChunk], user: dict = Depends(get_current_user)):
    """Save edited chunks JSON."""
    _check_report_access(report_id, user)
    chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
    data = [c.model_dump() for c in chunks]
    chunks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "count": len(data)}


@router.post("/{report_id}/regenerate-chunks")
async def regenerate_chunks(report_id: str, user: dict = Depends(get_current_user)):
    """Re-run chunking + AI indexing for an existing report."""
    _check_report_access(report_id, user)
    report_path = OUTPUT_DIR / f"{report_id}.md"
    meta_path = OUTPUT_DIR / f"{report_id}.json"
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
    chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"chunks": chunks, "count": len(chunks)}


@router.post("/{report_id}/push-fastgpt")
async def push_to_fastgpt(report_id: str, user: dict = Depends(get_current_user)):
    """Push chunks to FastGPT knowledge base."""
    _check_report_access(report_id, user)
    chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
    if not chunks_path.exists():
        raise HTTPException(404, "Chunks not found — generate chunks first")
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    # Get company name and existing push records
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    company_name = "未知公司"
    push_records: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        company_name = meta.get("company_name", company_name)
        push_records = meta.get("push_records", {})
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
    collection_name = f"{company_name}-{report_id[:8]}"
    try:
        result = await push_chunks_to_fastgpt(chunks, collection_name, fastgpt_cfg)
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
    """Update editable metadata fields."""
    _check_report_access(report_id, user)
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    if not meta_path.exists():
        raise HTTPException(404, "Report metadata not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    applied = 0
    for k, v in updates.items():
        if k not in _PROTECTED_META_KEYS:
            meta[k] = v
            applied += 1
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "applied": applied}


@router.post("/{report_id}/confirm")
async def confirm_report(report_id: str, user: dict = Depends(get_current_user)):
    """Confirm an updated report: status 'updated' → 'completed'."""
    _check_report_access(report_id, user)
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    if not meta_path.exists():
        raise HTTPException(404, "Report metadata not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("status") != "updated":
        raise HTTPException(400, "报告状态不是[已更新]，无需确认")
    meta["status"] = "completed"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


@router.get("/{report_id}/attachments")
async def list_attachments(report_id: str, user: dict = Depends(get_current_user)):
    """List attachments for a report."""
    _check_report_access(report_id, user)
    att_dir = OUTPUT_DIR / f"{report_id}_attachments"
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
    fp = OUTPUT_DIR / f"{report_id}_attachments" / filename
    if not fp.exists():
        raise HTTPException(404, "Attachment not found")
    return FileResponse(path=str(fp), filename=filename)


@router.delete("/{report_id}/attachments/{filename}")
async def delete_attachment(report_id: str, filename: str, user: dict = Depends(get_current_user)):
    """Delete a specific attachment file."""
    _check_report_access(report_id, user)
    fp = OUTPUT_DIR / f"{report_id}_attachments" / filename
    if not fp.exists():
        raise HTTPException(404, "Attachment not found")
    fp.unlink()
    # Update metadata
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        atts = meta.get("attachments", [])
        meta["attachments"] = [a for a in atts if a.get("filename") != filename]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


@router.post("/{report_id}/attachments")
async def upload_attachment(
    report_id: str,
    files: list[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload attachments to an existing report."""
    _check_report_access(report_id, user)
    att_dir = OUTPUT_DIR / f"{report_id}_attachments"
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
    meta_path = OUTPUT_DIR / f"{report_id}.json"
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
    return {"uploaded": len(uploaded), "files": uploaded}


@router.get("/{report_id}/download")
async def download_report(report_id: str):
    """Download the report as a .md file."""
    report_path = OUTPUT_DIR / f"{report_id}.md"
    if not report_path.exists():
        raise HTTPException(404, "Report not found")
    # Try to get company name for filename
    meta_path = OUTPUT_DIR / f"{report_id}.json"
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
