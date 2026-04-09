"""Intake Agent router: handles smart multi-format input for creating/updating targets."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from auth import get_current_user
from config import load_settings, OUTPUT_DIR, DEFAULT_AI_CONFIG

# In-memory snapshot store for update rollback: {task_id: {report_id, old_fields, old_md_content}}
_update_snapshots: dict[str, dict] = {}

# In-memory intake task queue for parallel execution
# {task_id: {status, company_name, op_type, step, total_steps, queue_position}}
_intake_tasks: dict[str, dict] = {}
_intake_semaphore: asyncio.Semaphore | None = None
_MAX_PARALLEL = 5


def _get_intake_semaphore() -> asyncio.Semaphore:
    global _intake_semaphore
    if _intake_semaphore is None:
        _intake_semaphore = asyncio.Semaphore(_MAX_PARALLEL)
    return _intake_semaphore
from db import get_db, get_next_bd_code
from routers.upload import _parse_from_bytes

log = logging.getLogger(__name__)
router = APIRouter()

# Supported image types for multimodal input
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
# Supported document types (text-extracted)
_DOC_EXTS = {".pdf", ".md", ".txt", ".docx", ".pptx"}


def _get_intake_cfg(settings: dict) -> dict:
    """Resolve intake_agent config, falling back to extractor config for API key."""
    ai = settings.get("ai_config", {})
    intake = ai.get("intake_agent", DEFAULT_AI_CONFIG.get("intake_agent", {}))
    # Inherit api_key from extractor if not set
    if not intake.get("api_key"):
        intake = {**intake, "api_key": ai.get("extractor", {}).get("api_key", "")}
    return intake


def _get_all_existing_targets() -> list[dict]:
    """Load all reports from DB as full target list for matching and old-value filling.
    Falls back to scanning output JSON files if DB is empty."""
    from config import OUTPUT_DIR
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT bd_code, company_name, project_name, industry, is_listed, "
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
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO intake_logs
               (report_id, log_type, trigger_reason, input_sources, changed_fields,
                steps_executed, steps_skipped, research_data_age_days, operator)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id,
                log_type,
                trigger_reason,
                json.dumps(input_sources, ensure_ascii=False),
                json.dumps(changed_fields, ensure_ascii=False),
                json.dumps(steps_executed, ensure_ascii=False),
                json.dumps(steps_skipped, ensure_ascii=False),
                research_data_age_days,
                operator,
            ),
        )
        conn.commit()
    finally:
        conn.close()


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
    settings = load_settings()
    intake_cfg = _get_intake_cfg(settings)

    if not intake_cfg.get("api_key"):
        raise HTTPException(400, "录入Agent未配置API Key，请在「AI设置 → 录入Agent」中配置")

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
    input_sources: list[str] = []
    failed_files: list[str] = []

    for f in files:
        raw = await f.read()
        if not raw:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext in _IMAGE_EXTS:
            image_items.append((f.filename, raw))
            input_sources.append(f.filename)
        elif ext in _DOC_EXTS:
            parsed = _parse_from_bytes(f.filename, raw)
            if parsed and parsed.strip():
                doc_texts.append((f.filename, parsed))
                input_sources.append(f.filename)
            else:
                # File uploaded but text extraction failed (e.g. encrypted/scanned PDF)
                # Treat as image for multimodal processing if possible, else note it
                log.warning("Doc text extraction failed for %s (%d bytes), will note in input", f.filename, len(raw))
                failed_files.append(f.filename)
                input_sources.append(f.filename)
                # Add a text note about the failed file so the agent knows it was provided
                doc_texts.append((f.filename, f"[文件内容：{f.filename}（文本提取失败，文件可能为扫描件或加密格式）]"))
        else:
            log.warning("Unsupported file type for intake: %s", f.filename)

    if text.strip():
        input_sources.append("文字内容")
    for u in url_list:
        input_sources.append(u)

    if not text.strip() and not image_items and not doc_texts and not url_list:
        raise HTTPException(400, "请提供至少一种输入：文字、图片、文档或链接")

    existing_targets = _get_all_existing_targets()

    from agents.intake_agent import run_intake_agent
    result = await run_intake_agent(
        text_input=text,
        image_items=image_items,
        doc_texts=doc_texts,
        urls=url_list,
        existing_targets=existing_targets,
        intake_cfg=intake_cfg,
    )

    # Post-process: for update ops, find bd_code by company_name and backfill old values
    target_by_name = {t["company_name"]: t for t in existing_targets if t.get("company_name")}
    _FIELD_ALIASES: dict[str, list[str]] = {
        "revenue_yuan": ["revenue_yuan", "revenue"],
        "net_profit_yuan": ["net_profit_yuan", "net_profit"],
        "valuation_yuan": ["valuation_yuan"],
    }
    for op in result.get("operations", []):
        if op.get("type") == "update":
            # Find bd_code via name matching
            company_name = op.get("company_name", "")
            bd_code = _find_bd_code_by_name(company_name, existing_targets)
            if bd_code:
                op["bd_code"] = bd_code
            # Backfill old values from existing record
            existing = target_by_name.get(company_name, {})
            if not existing and bd_code:
                existing = next((t for t in existing_targets if t.get("bd_code") == bd_code), {})
            changed = op.get("changed_fields", {})
            for field_key, change in changed.items():
                if isinstance(change, dict) and change.get("old") is None:
                    candidates = _FIELD_ALIASES.get(field_key, [field_key])
                    for candidate in candidates:
                        old_val = existing.get(candidate)
                        if old_val is not None and str(old_val) not in ("", "None", "nan"):
                            change["old"] = old_val
                            break

    result["mode"] = mode
    result["input_sources"] = input_sources
    return result


@router.get("/tasks")
async def list_intake_tasks(current_user: dict = Depends(get_current_user)):
    """Return current in-memory intake task queue status."""
    return {"tasks": list(_intake_tasks.values())}


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
    # Delete output files
    for suffix in [".md", "_chunks.json"]:
        f = OUTPUT_DIR / f"{task_id}{suffix}"
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass



@router.post("/execute")
async def execute_intake(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    Execute a parsed operation (single item from /parse result).
    For 'create': starts the full 6-step pipeline.
    For 'update': starts the light-update pipeline (Step3'+4+5+6).

    Body:
    {
        "operation": { type, company_name/bd_code, fields/changed_fields, source },
        "input_sources": [...],
        "force_full_research": false
    }
    """
    operation = body.get("operation", {})
    input_sources = body.get("input_sources", [])
    force_full_research = body.get("force_full_research", False)
    op_type = operation.get("type")
    operator = current_user.get("username")

    settings = load_settings()
    ai = settings.get("ai_config", {})
    intake_cfg = _get_intake_cfg(settings)

    if op_type == "create":
        return await _execute_create(operation, input_sources, operator, settings)
    elif op_type == "update":
        return await _execute_update(
            operation, input_sources, operator, settings, intake_cfg, force_full_research
        )
    else:
        raise HTTPException(400, f"Unknown operation type: {op_type}")


async def _execute_create(
    operation: dict,
    input_sources: list[str],
    operator: str | None,
    settings: dict,
) -> dict:
    """Create a new target by starting the full pipeline via a synthetic session."""
    from routers.upload import _persist_session
    from services.pipeline import run_pipeline
    from services.task_manager import task_manager
    import uuid

    fields = operation.get("fields", {})
    company_name = operation.get("company_name", fields.get("company_name", ""))
    if not company_name:
        raise HTTPException(400, "新建操作缺少公司名称")

    # Assign bd_code
    bd_code = fields.get("bd_code") or get_next_bd_code()
    fields["bd_code"] = bd_code
    fields["company_name"] = company_name
    if not fields.get("project_name"):
        fields["project_name"] = company_name

    # Build synthetic session
    session_id = uuid.uuid4().hex[:12]
    session_data = {
        "excel_path": None,
        "companies": [{"bd_code": bd_code, "company_name": company_name, "project_name": fields["project_name"]}],
        "all_rows": [fields],
        "attachments": {},
        "parsed_texts": {},
    }
    _persist_session(session_id, session_data)

    task_id = uuid.uuid4().hex[:12]  # task_id == report_id, consistent with report.py
    await task_manager.create_task(
        task_id=task_id,
        report_id=task_id,
        excel_row=fields,
        attachment_items=[],
        owner=operator,
    )

    async def _create_pipeline():
        await run_pipeline(task_id, fields, [], owner=operator, is_regeneration=False)

    await task_manager.start_task(task_id, _create_pipeline)

    # Register in intake task queue for frontend status tracking
    _intake_tasks[task_id] = {
        "task_id": task_id,
        "report_id": task_id,
        "bd_code": bd_code,
        "company_name": company_name,
        "op_type": "create",
        "status": "running",
        "step": 0,
        "total_steps": 6,
    }

    # Write intake log (create type)
    try:
        _write_intake_log(
            report_id=task_id,
            log_type="create",
            trigger_reason="录入Agent新建",
            input_sources=input_sources,
            changed_fields={k: {"old": None, "new": v} for k, v in fields.items()},
            steps_executed=["Step1", "Step2", "Step3", "Step4", "Step5", "Step6"],
            steps_skipped=[],
            research_data_age_days=None,
            operator=operator,
        )
    except Exception as e:
        log.warning("Failed to write intake log for create: %s", e)

    return {"task_id": task_id, "bd_code": bd_code, "type": "create"}


async def _execute_update(
    operation: dict,
    input_sources: list[str],
    operator: str | None,
    settings: dict,
    intake_cfg: dict,
    force_full_research: bool,
) -> dict:
    """Update an existing target using light-update or full-research pipeline."""
    from services.light_update_pipeline import run_light_update_pipeline
    from services.pipeline import run_pipeline
    from services.task_manager import task_manager
    import uuid

    bd_code = operation.get("bd_code")
    changed_fields = operation.get("changed_fields", {})

    if not bd_code:
        raise HTTPException(400, "更新操作缺少BD编码")
    if not changed_fields:
        raise HTTPException(400, "更新操作未包含任何字段变化")

    # Load existing report metadata
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

    # Save snapshot for rollback (in-memory, keyed by task_id assigned later)
    md_path = OUTPUT_DIR / f"{report_id}.md"
    old_md_content = md_path.read_text(encoding="utf-8") if md_path.exists() else None
    old_fields = {k: row[k] for k in changed_fields if k in row.keys()}
    # snapshot will be stored after task_id is known

    # Check if core fields changed (triggers full-research prompt)
    core_fields = set(intake_cfg.get("core_fields_trigger_research", ["description", "company_intro"]))
    changed_keys = set(changed_fields.keys())
    needs_research_prompt = bool(changed_keys & core_fields) and not force_full_research

    # Check research data age
    expire_days = int(intake_cfg.get("research_data_expire_days", 90))
    research_age_days = _get_research_age_days(report_id)
    research_expired = research_age_days is not None and research_age_days > expire_days

    trigger_reason_parts = []
    if force_full_research:
        trigger_reason_parts.append("用户指定完整重调研")
    elif changed_keys & core_fields:
        trigger_reason_parts.append(f"核心字段变化：{', '.join(changed_keys & core_fields)}")
    if research_expired:
        trigger_reason_parts.append(f"调研数据已过期（{research_age_days}天）")

    trigger_reason = "、".join(trigger_reason_parts) if trigger_reason_parts else "轻量更新"

    if force_full_research or research_expired:
        # Full pipeline — reuse existing report_id so it overwrites (same as report.py regen flow)
        task_id = report_id
        excel_row = dict(row)
        # Apply new field values
        for field_key, change in changed_fields.items():
            new_val = change.get("new") if isinstance(change, dict) else change
            if new_val is not None:
                excel_row[field_key] = new_val

        await task_manager.create_task(
            task_id=task_id,
            report_id=report_id,
            excel_row=excel_row,
            attachment_items=[],
            owner=operator,
            is_regeneration=True,
        )

        async def _full_regen_pipeline():
            await run_pipeline(task_id, excel_row, [], owner=operator, is_regeneration=True)

        await task_manager.start_task(task_id, _full_regen_pipeline)
        steps_executed = ["Step1", "Step2", "Step3", "Step4", "Step5", "Step6"]
        steps_skipped = []
        log_type = "full_regenerate"
    else:
        # Light update pipeline — use a new task_id so it doesn't conflict with the existing report task
        task_id = uuid.uuid4().hex[:12]
        await task_manager.create_task(
            task_id=task_id,
            report_id=report_id,
            excel_row={},
            attachment_items=[],
            owner=operator,
        )

        async def _light_update_pipeline():
            await run_light_update_pipeline(
                task_id=task_id,
                report_id=report_id,
                changed_fields=changed_fields,
                owner=operator,
                research_age_days=research_age_days,
            )

        await task_manager.start_task(task_id, _light_update_pipeline)
        steps_executed = ["Step3'", "Step4", "Step5", "Step6"]
        steps_skipped = [{"step": "Step1", "reason": "轻量更新跳过提取"},
                         {"step": "Step2", "reason": f"沿用{research_age_days}天前调研数据"}]
        log_type = "light_update"

    # Store snapshot for rollback
    _update_snapshots[task_id] = {
        "report_id": report_id,
        "old_fields": old_fields,
        "old_md_content": old_md_content,
    }

    # Register in intake task queue
    _intake_tasks[task_id] = {
        "task_id": task_id,
        "report_id": report_id,
        "bd_code": bd_code,
        "company_name": operation.get("company_name", ""),
        "op_type": log_type,
        "status": "running",
        "step": 0,
        "total_steps": 6 if force_full_research or research_expired else 4,
    }

    # Write intake log
    try:
        _write_intake_log(
            report_id=report_id,
            log_type=log_type,
            trigger_reason=trigger_reason,
            input_sources=input_sources,
            changed_fields=changed_fields,
            steps_executed=steps_executed,
            steps_skipped=steps_skipped,
            research_data_age_days=research_age_days,
            operator=operator,
        )
    except Exception as e:
        log.warning("Failed to write intake log for update: %s", e)

    return {
        "task_id": task_id,
        "report_id": report_id,
        "bd_code": bd_code,
        "type": log_type,
        "needs_research_prompt": needs_research_prompt,
        "research_age_days": research_age_days,
        "research_expired": research_expired,
    }


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
