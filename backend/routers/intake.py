"""Intake Agent router: handles smart multi-format input for creating/updating targets."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

from auth import get_current_user
from config import load_settings, OUTPUT_DIR, UPLOAD_DIR, DEFAULT_AI_CONFIG
from services.sse_manager import sse_manager
from services.intake_session_store import parse_from_bytes, persist_session
from services.intake_log_service import write_intake_log
from services.attachment_text_cache import persist_parsed_attachment_texts

# In-memory snapshot store for update rollback: {task_id: {report_id, old_fields, old_md_content}}
_update_snapshots: dict[str, dict] = {}

# In-memory intake task queue for parallel execution
# {task_id: {status, company_name, op_type, step, total_steps, queue_position}}
_intake_tasks: dict[str, dict] = {}
_intake_semaphore: asyncio.Semaphore | None = None
_MAX_PARALLEL = 5

# In-memory parse jobs for intake UI progress
_parse_jobs: dict[str, dict] = {}


def _get_intake_semaphore() -> asyncio.Semaphore:
    global _intake_semaphore
    if _intake_semaphore is None:
        _intake_semaphore = asyncio.Semaphore(_MAX_PARALLEL)
    return _intake_semaphore
from db import get_db, get_next_bd_code

log = logging.getLogger(__name__)
router = APIRouter()

# Supported image types for multimodal input
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
# Supported document types (text-extracted)
_DOC_EXTS = {".pdf", ".md", ".txt", ".docx", ".pptx"}


def cleanup_runtime_state_for_report(report_id: str) -> list[str]:
    """Clear in-memory intake task state and SSE caches tied to a report."""
    cleared_task_ids: list[str] = []

    for task_id, task in list(_intake_tasks.items()):
        if task_id == report_id or task.get("report_id") == report_id:
            _intake_tasks.pop(task_id, None)
            cleared_task_ids.append(task_id)

    for task_id, snapshot in list(_update_snapshots.items()):
        if task_id == report_id or snapshot.get("report_id") == report_id:
            _update_snapshots.pop(task_id, None)
            if task_id not in cleared_task_ids:
                cleared_task_ids.append(task_id)

    for task_id in [report_id, *cleared_task_ids]:
        sse_manager.clear_task(task_id)

    return cleared_task_ids


def _set_parse_job(
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    progress: int | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Update parse job status in memory."""
    job = _parse_jobs.get(job_id)
    if not job:
        return
    if status is not None:
        job["status"] = status
    if stage is not None:
        job["stage"] = stage
    if message is not None:
        job["message"] = message
    if progress is not None:
        job["progress"] = progress
    if result is not None:
        job["result"] = result
    if error is not None:
        job["error"] = error


async def _persist_v3_task_state(
    task_id: str,
    *,
    status: str,
    current_step: int | None = None,
    message: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persist intake task state using the existing task table semantics."""
    from services.task_manager import task_manager, TaskStatus

    status_map = {
        "queued": TaskStatus.PENDING,
        "running": TaskStatus.RUNNING,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
        "cancelled": TaskStatus.CANCELLED,
        "cancelling": TaskStatus.RUNNING,
    }
    await task_manager.update_task_status(
        task_id,
        status_map.get(status, TaskStatus.RUNNING),
        current_step=current_step,
        error_message=error_message,
        message=message,
    )


async def _send_v3_sse_progress(task_id: str, step: int, total: int, message: str) -> None:
    """Broadcast intake task progress to the shared report SSE stream."""
    await sse_manager.send_progress(task_id, step, total, message)


async def _send_v3_sse_complete(task_id: str, report_id: str) -> None:
    await sse_manager.send_complete(task_id, report_id)


async def _send_v3_sse_error(task_id: str, error: str) -> None:
    await sse_manager.send_error(task_id, error)


async def _expire_intake_task(task_id: str, delay_seconds: int = 60) -> None:
    """Drop finished task snapshots after a short retention window."""
    await asyncio.sleep(delay_seconds)
    _intake_tasks.pop(task_id, None)


def _schedule_intake_task_cleanup(task_id: str, delay_seconds: int = 60) -> None:
    """Keep completed/failed tasks visible briefly, then remove them from memory."""
    asyncio.create_task(_expire_intake_task(task_id, delay_seconds))


def _to_intake_task_view(row: dict) -> dict:
    """Adapt persisted task rows to the intake task response shape."""
    task_kind = row.get("task_kind") or "v3_create"
    op_type_map = {
        "v3_create": "create",
        "v3_update": "update",
        "attachment_update": "update",
    }
    return {
        "task_id": row.get("task_id"),
        "report_id": row.get("report_id"),
        "bd_code": row.get("bd_code"),
        "company_name": row.get("company_name") or "",
        "op_type": op_type_map.get(task_kind, "update"),
        "status": row.get("status"),
        "step": row.get("current_step") or 0,
        "total_steps": row.get("total_steps") or 4,
        "message": row.get("message"),
        "error_message": row.get("error_message"),
    }


def _get_intake_cfg(settings: dict) -> dict:
    """Resolve intake_agent config from the current settings payload."""
    ai = settings.get("ai_config", {})
    return {
        **DEFAULT_AI_CONFIG.get("intake_agent", {}),
        **(ai.get("intake_agent", {}) or {}),
    }


def _get_matcher_cfg(settings: dict, intake_cfg: dict) -> dict:
    """Resolve matcher config, defaulting to intake agent config."""
    ai = settings.get("ai_config", {})
    matcher = ai.get("matcher_agent", {}) or {}
    return {
        "base_url": matcher.get("base_url") or intake_cfg.get("base_url", ""),
        "api_key": matcher.get("api_key") or intake_cfg.get("api_key", ""),
        "model": matcher.get("model") or intake_cfg.get("model", "qwen3.5-plus"),
    }


def _get_v3_stage_count(settings: dict) -> int:
    fastgpt_cfg = settings.get("fastgpt", {}) or {}
    return 5 if fastgpt_cfg.get("enabled") else 4


def _classify_v3_stage(msg: str, total_steps: int) -> int:
    text = (msg or "").strip()
    if not text:
        return 0

    if "FastGPT" in text or "知识库" in text or "推送" in text:
        return min(total_steps, 5 if total_steps >= 5 else total_steps)
    if "评级" in text or "RatingAgent" in text:
        return min(total_steps, 4)
    if (
        "Tracking Processor" in text
        or "Info Chunk" in text
        or "tracking_chunk" in text
        or "info_chunk" in text
        or "并行写入" in text
        or "write_chunk" in text
        or ("chunk" in text and ("写入" in text or "完成" in text))
        or "保存数据" in text
        or "数据已保存" in text
    ):
        return min(total_steps, 3)
    if (
        "正在调研" in text
        or "Research 完成" in text
        or "web_search:" in text
        or "fetch_webpage:" in text
        or "cninfo_search:" in text
        or "akshare_query:" in text
        or "run_researcher" in text
    ):
        return min(total_steps, 2)
    if "WriterAgent" in text or "规划" in text or "事实链路" in text:
        return 1
    return 0


def _get_all_existing_targets() -> list[dict]:
    """Load all reports from DB as full target list for matching and old-value filling.
    Falls back to scanning output JSON files if DB is empty."""
    from config import OUTPUT_DIR
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT report_id, bd_code, company_name, project_name, industry, is_listed, "
            "province, city, district, website, valuation_yuan, valuation_date, "
            "revenue_yuan, net_profit_yuan, revenue, net_profit, description, "
            "company_intro, referral_status, stock_code, is_traded, "
            "dept_primary, dept_owner, remarks "
            "FROM reports ORDER BY updated_at DESC LIMIT 1000"
        ).fetchall()
        targets = [dict(r) for r in rows]
    finally:
        conn.close()

    # Fallback: if DB is empty, scan output JSON files
    if not targets:
        for meta_file in OUTPUT_DIR.glob("*.json"):
            if meta_file.stem.endswith("_chunks"):
                continue
            try:
                import json as _json
                meta = _json.loads(meta_file.read_text(encoding="utf-8"))
                if meta.get("bd_code") and meta.get("company_name"):
                    targets.append(meta)
            except Exception:
                pass

    return targets


def _normalize_company_name(name: str) -> str:
    """Strip common suffixes and punctuation for fuzzy matching."""
    import re
    name = name.strip()
    # Remove parenthetical location info like （台州）
    name = re.sub(r"[（(][^）)]*[）)]", "", name)
    # Remove common suffixes
    for suffix in ["股份有限公司", "有限责任公司", "有限公司", "股份公司", "集团有限公司", "集团", "股份", "科技", "公司"]:
        name = name.replace(suffix, "")
    return name.strip()


def _find_bd_code_by_name(company_name: str, existing_targets: list[dict]) -> str | None:
    """Find bd_code by company name using exact then fuzzy match."""
    # Exact match first
    for t in existing_targets:
        if t.get("company_name") == company_name:
            return t.get("bd_code")
    # Fuzzy match: normalize both sides
    norm_input = _normalize_company_name(company_name)
    if not norm_input:
        return None
    for t in existing_targets:
        norm_existing = _normalize_company_name(t.get("company_name", ""))
        if norm_existing and (norm_input in norm_existing or norm_existing in norm_input):
            return t.get("bd_code")
    return None


_BD_CODE_RE = re.compile(r"\bBD\s*[-_ ]?\s*(\d{2,})\b", re.IGNORECASE)


def _normalize_bd_code(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[\s\-_]", "", value.upper())
    if re.fullmatch(r"BD\d{2,}", compact):
        return compact
    return None


def _extract_explicit_bd_codes(*parts: str) -> list[str]:
    seen: list[str] = []
    for part in parts:
        if not part:
            continue
        for match in _BD_CODE_RE.finditer(part):
            code = _normalize_bd_code(match.group(0))
            if code and code not in seen:
                seen.append(code)
    return seen


def _find_target_record(target_key: str, existing_targets: list[dict]) -> dict | None:
    """Find existing target record by exact or fuzzy company/project name."""
    for t in existing_targets:
        if t.get("company_name") == target_key or t.get("project_name") == target_key:
            return t

    norm_input = _normalize_company_name(target_key)
    if not norm_input:
        return None

    for t in existing_targets:
        for name_key in ("company_name", "project_name"):
            candidate = t.get(name_key, "")
            norm_candidate = _normalize_company_name(candidate)
            if norm_candidate and (norm_input in norm_candidate or norm_candidate in norm_input):
                return t
    return None


def _build_v3_operations(
    merged_items: list[dict[str, Any]],
    input_sources: list[str],
    existing_targets: list[dict],
    attachment_path_map: dict[str, str],
    explicit_bd_codes: list[str] | None = None,
    raw_text_input: str | None = None,
    parsed_attachment_texts: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert parse output into intake execute-compatible operations."""
    operations: list[dict[str, Any]] = []
    all_attachment_names = list(attachment_path_map.keys())
    all_attachment_paths = dict(attachment_path_map)
    single_target_mode = len(merged_items) == 1
    parsed_bd_codes = explicit_bd_codes or []

    for item in merged_items:
        action = item.get("action", "create")
        project_name = item.get("project_name", "").strip()
        material_summary = item.get("material_summary", "").strip()
        related_attachments = item.get("related_attachments", []) or []
        effective_attachments = all_attachment_names if single_target_mode else related_attachments
        related_attachment_paths = {
            filename: attachment_path_map[filename]
            for filename in effective_attachments
            if filename in attachment_path_map
        }
        related_parsed_texts = {
            filename: parsed_attachment_texts[filename]
            for filename in effective_attachments
            if parsed_attachment_texts and filename in parsed_attachment_texts
        }
        source = item.get("source") or input_sources

        if not project_name:
            continue

        if action == "update":
            matched_name = item.get("matched_company_name") or project_name
            target = _find_target_record(matched_name, existing_targets)
            bd_code = item.get("bd_code") or (target or {}).get("bd_code")
            if not bd_code:
                bd_code = _find_bd_code_by_name(matched_name, existing_targets)

            operations.append({
                "type": "update",
                "company_name": matched_name,
                "bd_code": bd_code,
                "changed_fields": {},
                "source": source,
                "material_summary": material_summary,
                "tracking_material_summary": _build_tracking_material_summary(item, raw_text_input),
                "raw_user_text": (raw_text_input or "").strip(),
                "related_attachments": effective_attachments,
                "related_attachment_paths": related_attachment_paths,
                "parsed_attachment_texts": related_parsed_texts,
                "available_attachments": all_attachment_names,
                "available_attachment_paths": all_attachment_paths,
                "match_confidence": item.get("match_confidence"),
                "match_reason": item.get("match_reason"),
            })
            continue

        operations.append({
            "type": "create",
            "company_name": project_name,
            "fields": {
                "company_name": project_name,
                "project_name": project_name,
                **(
                    {"bd_code": item.get("bd_code")}
                    if _normalize_bd_code(item.get("bd_code"))
                    else {}
                ),
            },
            "source": source,
            "material_summary": material_summary,
            "tracking_material_summary": _build_tracking_material_summary(item, raw_text_input),
            "raw_user_text": (raw_text_input or "").strip(),
            "related_attachments": effective_attachments,
            "related_attachment_paths": related_attachment_paths,
            "parsed_attachment_texts": related_parsed_texts,
            "available_attachments": all_attachment_names,
            "available_attachment_paths": all_attachment_paths,
            "match_confidence": item.get("match_confidence"),
            "match_reason": item.get("match_reason"),
        })

        if action == "create" and not operations[-1]["fields"].get("bd_code") and single_target_mode:
            if len(parsed_bd_codes) == 1:
                operations[-1]["fields"]["bd_code"] = parsed_bd_codes[0]

    return operations


def _persist_uploaded_files(uploaded_files: list[tuple[str, bytes]], storage_key: str) -> dict[str, str]:
    """Persist uploaded raw files for later intake attachment copying."""
    if not uploaded_files:
        return {}

    target_dir = UPLOAD_DIR / "_intake_v3" / storage_key
    target_dir.mkdir(parents=True, exist_ok=True)

    attachment_path_map: dict[str, str] = {}
    for filename, raw in uploaded_files:
        if not filename or not raw:
            continue
        safe_name = Path(filename).name
        file_path = target_dir / safe_name
        file_path.write_bytes(raw)
        attachment_path_map[safe_name] = str(file_path)
    return attachment_path_map


def _copy_v3_attachments_to_report(report_id: str, attachment_paths: dict[str, str]) -> list[dict[str, Any]]:
    """Copy staged intake attachments into the report attachment directory."""
    if not attachment_paths:
        return []

    report_dir = OUTPUT_DIR / f"{report_id}_attachments"
    report_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, Any]] = []
    for filename, src in attachment_paths.items():
        src_path = Path(src)
        if not src_path.exists():
            log.warning("Staged attachment missing for report %s: %s", report_id, src)
            continue
        dst_path = report_dir / Path(filename).name
        if src_path.resolve() != dst_path.resolve():
            dst_path.write_bytes(src_path.read_bytes())
        copied.append({"filename": dst_path.name, "size": dst_path.stat().st_size})
    return copied


def _safe_parsed_text_filename(filename: str) -> str:
    stem = Path(filename).stem.strip() or "attachment"
    return f"{stem}.md"


def _persist_parsed_attachment_texts(
    report_id: str,
    parsed_attachment_texts: dict[str, str] | None,
) -> dict[str, str]:
    """Persist parsed attachment text as md cache files and return filename mapping."""
    return persist_parsed_attachment_texts(report_id, parsed_attachment_texts)


def _build_tracking_material_summary(item: dict[str, Any], raw_text_input: str | None) -> str:
    """Keep tracking context limited to user text and screenshot-derived notes."""
    parts: list[str] = []
    raw_text = (raw_text_input or "").strip()
    if raw_text:
        parts.append(f"【用户输入】\n{raw_text}")

    related_attachments = item.get("related_attachments", []) or []
    has_image = any(Path(str(name)).suffix.lower() in _IMAGE_EXTS for name in related_attachments)
    has_document = any(Path(str(name)).suffix.lower() in _DOC_EXTS for name in related_attachments)
    tracking_summary = str(item.get("tracking_material_summary") or "").strip()

    if tracking_summary:
        parts.append(f"【截图/聊天记录识别】\n{tracking_summary}")
    elif has_image and not has_document:
        material_summary = str(item.get("material_summary") or "").strip()
        if material_summary:
            parts.append(f"【截图/聊天记录识别】\n{material_summary}")

    return "\n\n".join(parts).strip()


def _resolve_operation_attachments(operation: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Resolve attachment selection for intake execution.

    Prefer explicit related attachments selected by parse/confirmation UI.
    If those paths are missing but the operation still carries available
    attachments, fall back to the full available set so single-target create
    flows do not silently drop uploaded files after draft merging.
    """
    related_paths = operation.get("related_attachment_paths", {}) or {}
    related_names = operation.get("related_attachments", []) or []

    if related_paths:
        return related_paths, related_names or list(related_paths.keys())

    available_paths = operation.get("available_attachment_paths", {}) or {}
    available_names = operation.get("available_attachments", []) or []
    if available_paths:
        return available_paths, available_names or list(available_paths.keys())

    return {}, related_names or available_names


def _write_intake_log(
    report_id: str,
    log_type: str,
    trigger_reason: str,
    input_sources: list[str],
    changed_fields: dict,
    steps_executed: list[str],
    steps_skipped: list[dict],
    research_data_age_days: int | None,
    operator: str | None,
) -> None:
    """Write a record to intake_logs table."""
    write_intake_log(
        report_id=report_id,
        log_type=log_type,
        trigger_reason=trigger_reason,
        input_sources=input_sources,
        changed_fields=changed_fields,
        steps_executed=steps_executed,
        steps_skipped=steps_skipped,
        research_data_age_days=research_data_age_days,
        operator=operator,
    )


@router.get("/debug-targets")
async def debug_targets(current_user: dict = Depends(get_current_user)):
    """Debug: show what _get_all_existing_targets returns."""
    targets = _get_all_existing_targets()
    result = []
    for t in targets:
        result.append({
            "bd_code": t.get("bd_code"),
            "company_name": t.get("company_name"),
            "revenue_yuan": t.get("revenue_yuan"),
            "revenue": t.get("revenue"),
            "valuation_yuan": t.get("valuation_yuan"),
        })
    return {"count": len(result), "targets": result}


@router.post("/parse")
async def parse_intake(
    text: str = Form(""),
    urls: str = Form(""),           # JSON array string: '["https://..."]'
    mode: str = Form("auto"),       # "auto" | "manual"
    files: list[UploadFile] = File(default=[]),
    current_user: dict = Depends(get_current_user),
):
    """
    Parse mixed input (text + images + documents + URLs) into structured operations.
    Returns the list of detected operations for user review (manual mode)
    or immediate execution (auto mode).
    """
    uploaded_files: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()
        if raw:
            uploaded_files.append((f.filename, raw))
    return await _parse_intake_internal(text, urls, mode, uploaded_files)


async def _parse_intake_internal(
    text: str,
    urls: str,
    mode: str,
    uploaded_files: list[tuple[str, bytes]],
    parse_job_id: str | None = None,
) -> dict:
    """Run intake parse pipeline and optionally update parse-job progress."""
    settings = load_settings()
    intake_cfg = _get_intake_cfg(settings)
    matcher_cfg = _get_matcher_cfg(settings, intake_cfg)

    if not intake_cfg.get("api_key"):
        raise HTTPException(400, "录入Agent未配置API Key，请在「AI设置 → 录入Agent」中配置")

    if parse_job_id:
        _set_parse_job(
            parse_job_id,
            status="running",
            stage="extracting",
            message="正在提取文件文本...",
            progress=10,
        )

    # Parse URLs
    url_list: list[str] = []
    if urls.strip():
        try:
            url_list = json.loads(urls)
        except Exception:
            # Fallback: treat as newline-separated
            url_list = [u.strip() for u in urls.splitlines() if u.strip().startswith("http")]

    # Separate uploaded files into images and documents
    image_items: list[tuple[str, bytes]] = []
    doc_texts: list[tuple[str, str]] = []
    parsed_attachment_texts: dict[str, str] = {}
    input_sources: list[str] = []
    storage_key = parse_job_id or uuid.uuid4().hex[:12]
    attachment_path_map = _persist_uploaded_files(uploaded_files, storage_key)

    total_files = max(len(uploaded_files), 1)
    for idx, (filename, raw) in enumerate(uploaded_files, 1):
        ext = Path(filename).suffix.lower()
        if ext in _IMAGE_EXTS:
            image_items.append((filename, raw))
            input_sources.append(filename)
        elif ext in _DOC_EXTS:
            parsed = parse_from_bytes(filename, raw)
            if parsed and parsed.strip():
                doc_texts.append((filename, parsed))
                parsed_attachment_texts[filename] = parsed
                input_sources.append(filename)
            else:
                log.warning("Doc text extraction failed for %s (%d bytes), will note in input", filename, len(raw))
                input_sources.append(filename)
                doc_texts.append((filename, f"[文件内容：{filename}（文本提取失败，文件可能为扫描件或加密格式）]"))
        else:
            log.warning("Unsupported file type for intake: %s", filename)

        if parse_job_id:
            p = 10 + int((idx / total_files) * 30)
            _set_parse_job(
                parse_job_id,
                stage="extracting",
                message=f"正在解析文件 ({idx}/{len(uploaded_files)})：{filename}",
                progress=p,
            )

    if text.strip():
        input_sources.append("文字内容")
    for u in url_list:
        input_sources.append(u)

    if not text.strip() and not image_items and not doc_texts and not url_list:
        raise HTTPException(400, "请提供至少一种输入：文字、图片、文档或链接")

    existing_targets = _get_all_existing_targets()
    attachment_filenames = [name for name, _ in uploaded_files]
    explicit_bd_codes = _extract_explicit_bd_codes(
        text,
        "\n".join(doc_text for _, doc_text in doc_texts),
    )

    if parse_job_id:
        _set_parse_job(
            parse_job_id,
            stage="analyzing",
            message="正在调用 IntakeAgent 识别标的...",
            progress=50,
        )

    from agents.intake_agent_v3 import run_intake_agent_v3
    intake_result = await run_intake_agent_v3(
        text_input=text,
        image_items=image_items,
        doc_texts=doc_texts,
        attachment_filenames=attachment_filenames,
        intake_cfg=intake_cfg,
    )

    if parse_job_id:
        _set_parse_job(
            parse_job_id,
            stage="matching",
            message="正在调用 MatcherAgent 匹配已有标的...",
            progress=72,
        )

    from agents.matcher_agent import run_matcher_agent

    matcher_client = AsyncOpenAI(
        base_url=matcher_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=matcher_cfg.get("api_key", ""),
    )
    matcher_result = await run_matcher_agent(
        project_names=[
            t.get("project_name", "").strip()
            for t in intake_result.get("targets", [])
            if t.get("project_name", "").strip()
        ],
        existing_targets=existing_targets,
        client=matcher_client,
        model=matcher_cfg.get("model", "qwen3.5-plus"),
    )

    if parse_job_id:
        _set_parse_job(
            parse_job_id,
            stage="postprocessing",
            message="正在整理识别结果...",
            progress=85,
        )

    from agents.intake_merger import merge_intake_and_matcher, validate_confirmation_data

    confirmation_items = validate_confirmation_data(
        merge_intake_and_matcher(intake_result, matcher_result)
    )
    operations = _build_v3_operations(
        confirmation_items,
        input_sources,
        existing_targets,
        attachment_path_map,
        explicit_bd_codes=explicit_bd_codes,
        raw_text_input=text,
        parsed_attachment_texts=parsed_attachment_texts,
    )

    create_count = sum(1 for op in operations if op.get("type") == "create")
    update_count = sum(1 for op in operations if op.get("type") == "update")

    result = {
        "operations": operations,
        "summary": f"本次识别到 {len(operations)} 个操作，其中 {create_count} 个新建、{update_count} 个更新",
        "mode": mode,
        "input_sources": input_sources,
        "confirmation_items": confirmation_items,
        "targets": intake_result.get("targets", []),
        "matcher_result": matcher_result.get("matches", []),
        "raw_content_summary": f"文字:{bool(text_input := text.strip())} 图片:{len(image_items)} 文档:{len(doc_texts)} 链接:{len(url_list)}",
    }
    return result


@router.post("/parse-async")
async def start_parse_intake(
    text: str = Form(""),
    urls: str = Form(""),
    mode: str = Form("auto"),
    files: list[UploadFile] = File(default=[]),
    current_user: dict = Depends(get_current_user),
):
    """Start asynchronous parse for intake with progress polling."""
    import uuid

    uploaded_files: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()
        if raw:
            uploaded_files.append((f.filename, raw))

    parse_job_id = uuid.uuid4().hex[:12]
    _parse_jobs[parse_job_id] = {
        "parse_job_id": parse_job_id,
        "status": "queued",
        "stage": "queued",
        "message": "解析任务已创建",
        "progress": 0,
        "result": None,
        "error": None,
    }

    async def _run_parse_job():
        try:
            result = await _parse_intake_internal(text, urls, mode, uploaded_files, parse_job_id)
            _set_parse_job(
                parse_job_id,
                status="completed",
                stage="completed",
                message="解析完成",
                progress=100,
                result=result,
            )
        except Exception as e:
            log.exception("Intake async parse failed: %s", parse_job_id)
            _set_parse_job(
                parse_job_id,
                status="failed",
                stage="failed",
                message="解析失败",
                progress=100,
                error=str(e),
            )

    asyncio.create_task(_run_parse_job())
    return {"parse_job_id": parse_job_id}


@router.get("/parse-status/{parse_job_id}")
async def get_parse_status(
    parse_job_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Poll parse progress/result for async parse jobs."""
    job = _parse_jobs.get(parse_job_id)
    if not job:
        raise HTTPException(404, "解析任务不存在或已过期")
    return job


@router.get("/tasks")
async def list_intake_tasks(current_user: dict = Depends(get_current_user)):
    """Return current in-memory intake task queue status."""
    from services.task_manager import task_manager

    persisted = await task_manager.list_recent_intake_tasks(owner=current_user.get("username"), limit=100)
    task_map = {row["task_id"]: _to_intake_task_view(row) for row in persisted}
    for task_id, task in _intake_tasks.items():
        task_map[task_id] = {**task_map.get(task_id, {}), **task}
    return {"tasks": list(task_map.values())}


@router.post("/cancel/{task_id}")
async def cancel_intake_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Cancel a running intake task, rolling back any partial changes."""
    task_info = _intake_tasks.get(task_id)
    if not task_info:
        raise HTTPException(404, "任务不存在或已完成")

    # Signal cancellation
    task_info["status"] = "cancelling"
    await _persist_v3_task_state(task_id, status="cancelling", current_step=task_info.get("step"), message=task_info.get("message"))

    # Cancel the asyncio task
    from services.task_manager import task_manager
    cancelled = await task_manager.cancel_task(task_id)

    # Rollback
    snapshot = _update_snapshots.pop(task_id, None)
    if snapshot:
        # Update task: restore old DB fields and MD content
        _rollback_update(snapshot)
    else:
        # Create task: delete report record and output files
        _delete_partial_report(task_id)

    _intake_tasks.pop(task_id, None)
    return {"ok": True, "rolled_back": snapshot is not None}


def _rollback_update(snapshot: dict) -> None:
    """Restore old field values to DB and old MD content to file."""
    report_id = snapshot.get("report_id")
    old_fields = snapshot.get("old_fields", {})
    old_md_content = snapshot.get("old_md_content")

    if old_fields and report_id:
        conn = get_db()
        try:
            set_parts = ", ".join(f"{k} = ?" for k in old_fields)
            vals = list(old_fields.values()) + [report_id]
            conn.execute(f"UPDATE reports SET {set_parts} WHERE report_id = ?", vals)
            conn.commit()
        except Exception as e:
            log.warning("Rollback DB failed: %s", e)
        finally:
            conn.close()

    if old_md_content and report_id:
        md_path = OUTPUT_DIR / f"{report_id}.md"
        try:
            md_path.write_text(old_md_content, encoding="utf-8")
        except Exception as e:
            log.warning("Rollback MD file failed: %s", e)


def _delete_partial_report(task_id: str) -> None:
    """Delete a partially-created report and its output files."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM reports WHERE report_id = ?", (task_id,))
        conn.commit()
    except Exception as e:
        log.warning("Delete partial report from DB failed: %s", e)
    finally:
        conn.close()
    # Delete local artifacts created by the intake flow.
    for artifact in [
        OUTPUT_DIR / f"{task_id}.md",
        OUTPUT_DIR / f"{task_id}.json",
        OUTPUT_DIR / f"{task_id}_debug",
        OUTPUT_DIR / f"{task_id}_attachments",
    ]:
        try:
            if artifact.is_dir():
                import shutil

                shutil.rmtree(artifact, ignore_errors=True)
            elif artifact.exists():
                artifact.unlink()
        except Exception:
            pass



def _get_research_age_days(report_id: str) -> int | None:
    """Get how many days ago the last full research was run for this report."""
    # Check the debug dir for research_data.json modification time
    from config import OUTPUT_DIR
    research_file = OUTPUT_DIR / f"{report_id}_debug" / "research_data.json"
    if research_file.exists():
        import time
        mtime = research_file.stat().st_mtime
        age_seconds = time.time() - mtime
        return int(age_seconds / 86400)
    # Fall back to report created_at
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT created_at FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row:
            from datetime import datetime, timezone
            created = datetime.fromisoformat(row["created_at"])
            now = datetime.now()
            return (now - created).days
    except Exception:
        pass
    finally:
        conn.close()
    return None


@router.get("/logs/{report_id}")
async def get_intake_logs(
    report_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get all intake logs for a report."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM intake_logs WHERE report_id = ? ORDER BY created_at DESC",
            (report_id,),
        ).fetchall()
        logs = []
        for r in rows:
            entry = dict(r)
            for json_field in ("input_sources", "changed_fields", "steps_executed", "steps_skipped"):
                if entry.get(json_field):
                    try:
                        entry[json_field] = json.loads(entry[json_field])
                    except Exception:
                        pass
            logs.append(entry)
        return {"logs": logs, "count": len(logs)}
    finally:
        conn.close()


# ── Intake Pipeline ──────────────────────────────────────────────

@router.post("/execute")
@router.post("/execute-v3")
async def execute_intake(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """Execute using the current pipeline entrypoint.

    Accepts the same body format as /execute for compatibility with
    existing parse output.

    Body:
    {
        "operation": { type, company_name, fields/changed_fields, source },
        "input_sources": [...],
        "force_full_research": false
    }
    """
    from services.pipeline_v3 import run_pipeline_v3
    from services.task_manager import task_manager
    import uuid

    operation = body.get("operation", {})
    input_sources = body.get("input_sources", [])
    op_type = operation.get("type")
    operator = current_user.get("username")

    settings = load_settings()
    total_steps = _get_v3_stage_count(settings)
    auto_push_enabled = total_steps >= 5

    if op_type == "create":
        fields = operation.get("fields", {})
        company_name = operation.get("company_name", fields.get("company_name", ""))
        if not company_name:
            raise HTTPException(400, "新建操作缺少公司名称")

        explicit_bd_code = _normalize_bd_code(fields.get("bd_code"))
        bd_code = explicit_bd_code or get_next_bd_code()
        fields["bd_code"] = bd_code
        fields["company_name"] = company_name
        if not fields.get("project_name"):
            fields["project_name"] = company_name

        task_id = uuid.uuid4().hex[:12]
        attachment_paths, attachment_filenames = _resolve_operation_attachments(operation)
        copied_attachments = _copy_v3_attachments_to_report(task_id, attachment_paths)
        _persist_parsed_attachment_texts(task_id, operation.get("parsed_attachment_texts") or {})

        # Build material summary from source info
        material_summary = _build_material_summary(operation, input_sources)

        # Register task for frontend tracking
        _intake_tasks[task_id] = {
            "task_id": task_id,
            "report_id": task_id,
            "bd_code": bd_code,
            "company_name": company_name,
            "op_type": "create",
            "status": "running",
            "step": 0,
            "total_steps": total_steps,
            "message": "任务已创建，等待执行",
        }
        await task_manager.create_intake_task(
            task_id=task_id,
            report_id=task_id,
            owner=operator,
            company_name=company_name,
            bd_code=bd_code,
            task_kind="v3_create",
            total_steps=total_steps,
            message="任务已创建，等待执行",
        )

        # Run pipeline in background
        async def _run():
            try:
                _intake_tasks[task_id]["step"] = 1
                _intake_tasks[task_id]["message"] = "事实链路规划中..."
                await _persist_v3_task_state(
                    task_id,
                    status="running",
                    current_step=1,
                    message=_intake_tasks[task_id]["message"],
                )
                await _send_v3_sse_progress(
                    task_id,
                    1,
                    total_steps,
                    _intake_tasks[task_id]["message"],
                )
                result = await run_pipeline_v3(
                    task_id=task_id,
                    action="create",
                    company_name=company_name,
                    bd_code=bd_code,
                    fields=fields,
                    material_summary=material_summary,
                    attachment_filenames=attachment_filenames,
                    attachments_info=copied_attachments,
                    settings=settings,
                    owner=operator,
                    on_progress=lambda msg: _update_task_progress(task_id, msg),
                    parsed_attachment_texts=operation.get("parsed_attachment_texts") or {},
                    tracking_material_summary=operation.get("tracking_material_summary", ""),
                )
                try:
                    steps_executed = ["TrackingProcessor", "InfoChunkWriter"]
                    if result.get("rating") is not None:
                        steps_executed.append("RatingAgent")
                    auto_push = result.get("auto_push", {}) or {}
                    if auto_push.get("status") in {"pushed", "skipped"}:
                        steps_executed.append("FastGPTPush")
                    _write_intake_log(
                        report_id=task_id,
                        log_type="create",
                        trigger_reason="录入Agent新建(v4)",
                        input_sources=input_sources,
                        changed_fields=result.get("backfilled_fields", {}) or {
                            k: {"old": None, "new": v} for k, v in fields.items()
                        },
                        steps_executed=steps_executed,
                        steps_skipped=[],
                        research_data_age_days=None,
                        operator=operator,
                    )
                except Exception as e:
                    log.warning("Failed to write intake log: %s", e)
                _intake_tasks[task_id]["status"] = "completed"
                _intake_tasks[task_id]["step"] = total_steps
                _intake_tasks[task_id]["message"] = "任务完成"
                await _persist_v3_task_state(
                    task_id,
                    status="completed",
                    current_step=total_steps,
                    message="任务完成",
                )
                await _send_v3_sse_complete(task_id, task_id)
                _schedule_intake_task_cleanup(task_id)
            except Exception as e:
                log.exception(f"pipeline failed for {task_id}")
                _intake_tasks[task_id]["status"] = "failed"
                _intake_tasks[task_id]["message"] = f"任务失败: {e}"
                await _persist_v3_task_state(
                    task_id,
                    status="failed",
                    current_step=_intake_tasks[task_id].get("step", 0),
                    message=_intake_tasks[task_id]["message"],
                    error_message=str(e),
                )
                await _send_v3_sse_error(task_id, str(e))
                _schedule_intake_task_cleanup(task_id)

        asyncio.create_task(_run())

        return {
            "task_id": task_id,
            "report_id": task_id,
            "bd_code": bd_code,
            "type": "create",
            "pipeline": "v4",
            "auto_push_enabled": auto_push_enabled,
        }

    elif op_type == "update":
        bd_code = operation.get("bd_code")
        changed_fields = operation.get("changed_fields", {})

        if not bd_code:
            raise HTTPException(400, "更新操作缺少BD编码")

        # Load existing report
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM reports WHERE bd_code = ? ORDER BY created_at DESC LIMIT 1",
                (bd_code,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            raise HTTPException(404, f"未找到BD编码为 {bd_code} 的标的")

        report_id = row["report_id"]
        company_name = row["company_name"]
        task_id = uuid.uuid4().hex[:12]
        attachment_paths, attachment_filenames = _resolve_operation_attachments(operation)
        copied_attachments = _copy_v3_attachments_to_report(report_id, attachment_paths)
        _persist_parsed_attachment_texts(report_id, operation.get("parsed_attachment_texts") or {})

        # Build fields from changed_fields
        fields = {}
        for k, v in changed_fields.items():
            if isinstance(v, dict):
                fields[k] = v.get("new")
            else:
                fields[k] = v

        material_summary = _build_material_summary(operation, input_sources)
        # Register task
        _intake_tasks[task_id] = {
            "task_id": task_id,
            "report_id": report_id,
            "bd_code": bd_code,
            "company_name": company_name,
            "op_type": "update",
            "status": "running",
            "step": 0,
            "total_steps": total_steps,
            "message": "任务已创建，等待执行",
        }
        await task_manager.create_intake_task(
            task_id=task_id,
            report_id=report_id,
            owner=operator,
            company_name=company_name,
            bd_code=bd_code,
            task_kind="v3_update",
            total_steps=total_steps,
            message="任务已创建，等待执行",
        )

        async def _run():
            try:
                _intake_tasks[task_id]["step"] = 1
                _intake_tasks[task_id]["message"] = "事实链路规划中..."
                await _persist_v3_task_state(
                    task_id,
                    status="running",
                    current_step=1,
                    message=_intake_tasks[task_id]["message"],
                )
                await _send_v3_sse_progress(
                    task_id,
                    1,
                    total_steps,
                    _intake_tasks[task_id]["message"],
                )
                result = await run_pipeline_v3(
                    task_id=report_id,
                    action="update",
                    company_name=company_name,
                    bd_code=bd_code,
                    fields=fields,
                    material_summary=material_summary,
                    attachment_filenames=attachment_filenames,
                    attachments_info=copied_attachments,
                    settings=settings,
                    owner=operator,
                    on_progress=lambda msg: _update_task_progress(task_id, msg),
                    parsed_attachment_texts=operation.get("parsed_attachment_texts") or {},
                    tracking_material_summary=operation.get("tracking_material_summary", ""),
                )
                try:
                    steps_executed = ["TrackingProcessor"]
                    if "info" in (result.get("chunks_written") or []):
                        steps_executed.append("InfoChunkWriter")
                    if result.get("rating") is not None:
                        steps_executed.append("RatingAgent")
                    auto_push = result.get("auto_push", {}) or {}
                    if auto_push.get("status") in {"pushed", "skipped"}:
                        steps_executed.append("FastGPTPush")
                    _write_intake_log(
                        report_id=report_id,
                        log_type="update",
                        trigger_reason="录入Agent更新(v4)",
                        input_sources=input_sources,
                        changed_fields=result.get("backfilled_fields", {}),
                        steps_executed=steps_executed,
                        steps_skipped=[],
                        research_data_age_days=None,
                        operator=operator,
                    )
                except Exception as e:
                    log.warning("Failed to write intake log: %s", e)
                _intake_tasks[task_id]["status"] = "completed"
                _intake_tasks[task_id]["step"] = total_steps
                _intake_tasks[task_id]["message"] = "任务完成"
                await _persist_v3_task_state(
                    task_id,
                    status="completed",
                    current_step=total_steps,
                    message="任务完成",
                )
                await _send_v3_sse_complete(task_id, report_id)
                _schedule_intake_task_cleanup(task_id)
            except Exception as e:
                log.exception(f"pipeline update failed for {task_id}")
                _intake_tasks[task_id]["status"] = "failed"
                _intake_tasks[task_id]["message"] = f"任务失败: {e}"
                await _persist_v3_task_state(
                    task_id,
                    status="failed",
                    current_step=_intake_tasks[task_id].get("step", 0),
                    message=_intake_tasks[task_id]["message"],
                    error_message=str(e),
                )
                await _send_v3_sse_error(task_id, str(e))
                _schedule_intake_task_cleanup(task_id)

        asyncio.create_task(_run())

        return {
            "task_id": task_id,
            "report_id": report_id,
            "bd_code": bd_code,
            "type": "update",
            "pipeline": "v4",
            "auto_push_enabled": auto_push_enabled,
        }

    else:
        raise HTTPException(400, f"Unknown operation type: {op_type}")


def _build_material_summary(operation: dict, input_sources: list) -> str:
    """Build material summary from operation data."""
    material_summary = operation.get("material_summary")
    raw_user_text = str(operation.get("raw_user_text") or "").strip()
    if material_summary and str(material_summary).strip():
        if raw_user_text:
            return (
                "【用户原始输入】\n"
                f"{raw_user_text}\n\n"
                "【Intake保真摘录】\n"
                f"{str(material_summary).strip()}"
            )
        return str(material_summary).strip()
    if raw_user_text:
        return raw_user_text

    parts = []

    # From fields
    fields = operation.get("fields", {})
    if fields.get("description"):
        parts.append(f"项目简介: {fields['description']}")
    if fields.get("company_intro"):
        parts.append(f"公司简介: {fields['company_intro']}")
    if fields.get("industry"):
        parts.append(f"行业: {fields['industry']}")
    if fields.get("revenue"):
        parts.append(f"营收: {fields['revenue']}")

    # From changed_fields
    changed = operation.get("changed_fields", {})
    for k, v in changed.items():
        if isinstance(v, dict) and v.get("new"):
            parts.append(f"{k}: {v['new']}")

    # Source info
    if input_sources:
        parts.append(f"来源: {', '.join(input_sources)}")

    return "\n".join(parts) if parts else "用户录入"


def _update_task_progress(task_id: str, msg: str):
    """Update task progress message and mirror it to SSE subscribers."""
    task = _intake_tasks.get(task_id)
    if task:
        task["message"] = msg
        classified_step = _classify_v3_stage(msg, task.get("total_steps", 4))
        if classified_step > 0:
            task["step"] = max(task.get("step", 0), classified_step)
        asyncio.create_task(
            _persist_v3_task_state(
                task_id,
                status=task.get("status", "running"),
                current_step=task.get("step"),
                message=msg,
            )
        )
        asyncio.create_task(
            _send_v3_sse_progress(
                task_id,
                task.get("step", 0),
                task.get("total_steps", 4),
                msg,
            )
        )

