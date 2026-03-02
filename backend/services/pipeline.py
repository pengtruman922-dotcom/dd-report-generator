"""6-step pipeline orchestration: Extract → Research → Write → FieldExtract → Chunk & Index → FastGPT Push."""

from __future__ import annotations

import json
import logging
import re
import traceback
from datetime import datetime
from typing import Any

from agents.extractor import extract

log = logging.getLogger(__name__)
from agents.researcher import research, validate_tools_config
from agents.writer import write_report
from agents.field_extractor import extract_fields
from services.chunker import chunk_and_index
from services.fastgpt_uploader import push_chunks_to_fastgpt, save_push_record, delete_collection
from services.sse_manager import sse_manager
from services.task_manager import task_manager, TaskStatus
from services.token_tracker import TokenTracker
from config import load_settings, OUTPUT_DIR, DEFAULT_FASTGPT_CONFIG, DEFAULT_TOOLS_CONFIG


def _extract_score_from_md(md: str) -> tuple[float | None, str | None]:
    """Try to extract the composite score and rating from the report markdown."""
    m = re.search(r"综合得分.*?\*\*\s*([\d.]+)\s*\*\*", md)
    score = float(m.group(1)) if m else None
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
    return score, rating


def _latest_value(data: Any) -> str | None:
    """Get the latest year's value from a dict like {"2022": "11亿", "2023": "12亿"}."""
    if isinstance(data, dict):
        if data:
            latest_key = max(data.keys())
            return str(data[latest_key])
    if isinstance(data, str):
        return data
    return None


def _save_metadata(
    report_id: str,
    excel_row: dict[str, Any],
    company_profile: dict[str, Any],
    report_md: str,
    owner: str | None = None,
    attachments_info: list[dict] | None = None,
    is_regeneration: bool = False,
):
    """Save report metadata to both database and JSON file (dual-write)."""
    from db import get_db

    score, rating = _extract_score_from_md(report_md)
    fin = company_profile.get("financial_data", {})
    if not isinstance(fin, dict):
        fin = {}
    # Start with all Excel row fields as base
    meta = {}
    for k, v in excel_row.items():
        if v is not None:
            meta[k] = str(v) if not isinstance(v, str) else v
        else:
            meta[k] = None
    # Overlay: AI-extracted fields override Excel when non-null
    # This ensures more accurate data (e.g. corrected industry) replaces raw Excel
    _overlay_keys = [
        "company_name", "industry", "province", "city", "district",
        "is_listed", "stock_code", "website",
    ]
    for k in _overlay_keys:
        extracted = company_profile.get(k)
        if extracted and extracted != "null":
            meta[k] = str(extracted) if not isinstance(extracted, str) else extracted
    # Preserve push_records from previous metadata if regenerating
    existing_push_records = {}
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    if is_regeneration and meta_path.exists():
        try:
            old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            existing_push_records = old_meta.get("push_records", {})
        except Exception:
            pass
    # System fields (always overwrite)
    created_at = datetime.now().isoformat()
    meta.update({
        "report_id": report_id,
        "score": score,
        "rating": rating,
        "status": "updated" if is_regeneration else "completed",
        "created_at": created_at,
        "file_size": len(report_md.encode("utf-8")),
    })
    if owner:
        meta["owner"] = owner
    if attachments_info:
        meta["attachments"] = attachments_info
    if existing_push_records:
        meta["push_records"] = existing_push_records

    # Write to JSON file (backward compatibility)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write to database (new primary storage)
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Prepare JSON fields
        locked_fields_json = json.dumps(meta.get("locked_fields", []))
        push_records_json = json.dumps(existing_push_records)
        attachments_json = json.dumps(attachments_info or [])
        metadata_json = json.dumps(meta, ensure_ascii=False)

        # Prepare file paths
        md_path = str(OUTPUT_DIR / f"{report_id}.md")
        chunks_path = str(OUTPUT_DIR / f"{report_id}_chunks.json")
        debug_dir = str(OUTPUT_DIR / f"{report_id}_debug")
        attachments_dir = str(OUTPUT_DIR / f"{report_id}_attachments")

        # Check if report exists
        existing = cursor.execute(
            "SELECT report_id FROM reports WHERE report_id = ?",
            (report_id,)
        ).fetchone()

        if existing:
            # Update existing record
            cursor.execute("""
                UPDATE reports SET
                    bd_code = ?, company_name = ?, project_name = ?,
                    industry = ?, province = ?, city = ?, district = ?,
                    is_listed = ?, stock_code = ?, website = ?,
                    revenue = ?, net_profit = ?, revenue_yuan = ?, net_profit_yuan = ?,
                    valuation_yuan = ?, valuation_date = ?,
                    description = ?, company_intro = ?, industry_tags = ?,
                    referral_status = ?, is_traded = ?, dept_primary = ?, dept_owner = ?,
                    annual_report_attachment = ?, remarks = ?,
                    score = ?, rating = ?, status = ?, owner = ?,
                    updated_at = ?, file_size = ?,
                    intro_attachment = ?, metadata_json = ?,
                    locked_fields = ?, push_records = ?, attachments = ?,
                    md_path = ?, chunks_path = ?, debug_dir = ?, attachments_dir = ?
                WHERE report_id = ?
            """, (
                meta.get("bd_code"), meta.get("company_name"), meta.get("project_name"),
                meta.get("industry"), meta.get("province"), meta.get("city"), meta.get("district"),
                meta.get("is_listed"), meta.get("stock_code"), meta.get("website"),
                meta.get("revenue"), meta.get("net_profit"), meta.get("revenue_yuan"), meta.get("net_profit_yuan"),
                meta.get("valuation_yuan"), meta.get("valuation_date"),
                meta.get("description"), meta.get("company_intro"), meta.get("industry_tags"),
                meta.get("referral_status"), meta.get("is_traded"), meta.get("dept_primary"), meta.get("dept_owner"),
                meta.get("annual_report_attachment"), meta.get("remarks"),
                score, rating, meta.get("status"), owner,
                created_at, meta.get("file_size"),
                meta.get("intro_attachment"), metadata_json,
                locked_fields_json, push_records_json, attachments_json,
                md_path, chunks_path, debug_dir, attachments_dir,
                report_id
            ))
        else:
            # Insert new record
            cursor.execute("""
                INSERT INTO reports (
                    report_id, bd_code, company_name, project_name,
                    industry, province, city, district,
                    is_listed, stock_code, website,
                    revenue, net_profit, revenue_yuan, net_profit_yuan,
                    valuation_yuan, valuation_date,
                    description, company_intro, industry_tags,
                    referral_status, is_traded, dept_primary, dept_owner,
                    annual_report_attachment, remarks,
                    score, rating, manual_rating, status, owner,
                    created_at, updated_at, file_size,
                    intro_attachment, metadata_json,
                    locked_fields, push_records, attachments,
                    md_path, chunks_path, debug_dir, attachments_dir
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?
                )
            """, (
                report_id, meta.get("bd_code"), meta.get("company_name"), meta.get("project_name"),
                meta.get("industry"), meta.get("province"), meta.get("city"), meta.get("district"),
                meta.get("is_listed"), meta.get("stock_code"), meta.get("website"),
                meta.get("revenue"), meta.get("net_profit"), meta.get("revenue_yuan"), meta.get("net_profit_yuan"),
                meta.get("valuation_yuan"), meta.get("valuation_date"),
                meta.get("description"), meta.get("company_intro"), meta.get("industry_tags"),
                meta.get("referral_status"), meta.get("is_traded"), meta.get("dept_primary"), meta.get("dept_owner"),
                meta.get("annual_report_attachment"), meta.get("remarks"),
                score, rating, meta.get("manual_rating"), meta.get("status"), owner,
                created_at, created_at, meta.get("file_size"),
                meta.get("intro_attachment"), metadata_json,
                locked_fields_json, push_records_json, attachments_json,
                md_path, chunks_path, debug_dir, attachments_dir
            ))

        conn.commit()
        conn.close()
        log.info(f"Saved metadata to database for report {report_id}")
    except Exception as e:
        log.error(f"Failed to save metadata to database for {report_id}: {e}")
        # Don't fail the entire pipeline if database write fails


async def run_pipeline(
    task_id: str,
    excel_row: dict[str, Any],
    attachment_items: list[tuple[str, str]],
    failed_attachments: list[str] | None = None,
    owner: str | None = None,
    attachments_info: list[dict] | None = None,
    is_regeneration: bool = False,
):
    """Run the full 4-step pipeline, sending SSE progress events.

    attachment_items: list of (filename, text) tuples.
    failed_attachments: list of failure descriptions for attachments that couldn't be parsed.
    """
    settings = load_settings()
    ai = settings.get("ai_config", {})
    tools_cfg = settings.get("tools", DEFAULT_TOOLS_CONFIG)
    ext_cfg = ai.get("extractor", {})
    res_cfg = ai.get("researcher", {})
    wrt_cfg = ai.get("writer", {})
    fe_cfg = ai.get("field_extractor", {})
    chk_cfg = ai.get("chunker", {})
    # Fallback to extractor key if chunker has no API key configured
    if not chk_cfg.get("api_key"):
        chk_cfg = {**chk_cfg, "api_key": ext_cfg.get("api_key", ""),
                    "base_url": chk_cfg.get("base_url") or ext_cfg.get("base_url", ""),
                    "model": chk_cfg.get("model") or ext_cfg.get("model", "")}

    try:
        # Update task status to running
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=0)

        # Initialize token tracker
        token_tracker = TokenTracker()

        # ── Validate API keys (steps 1-3 required) ────────────────
        for step_name, cfg in [("extractor", ext_cfg), ("researcher", res_cfg), ("writer", wrt_cfg)]:
            if not cfg.get("api_key"):
                await sse_manager.send_error(
                    task_id,
                    f"请先在「AI 设置」页面配置 {step_name} 的 API Key，然后重试。",
                )
                return
        # ── Validate tools config (search/scraper API keys) ──────
        tools_errors = validate_tools_config(tools_cfg)
        if tools_errors:
            await sse_manager.send_error(
                task_id,
                "搜索工具配置不完整，请在「搜索工具」设置页面检查：\n" + "\n".join(tools_errors),
            )
            return
        # ── Warn about failed attachments ─────────────────────────────
        if failed_attachments:
            for fail_msg in failed_attachments:
                await sse_manager.send_progress(
                    task_id, 0, 6, f"⚠️ 附件解析失败: {fail_msg}"
                )

        # ── Step 1: Extract ──────────────────────────────────────────
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=1)
        att_summary = f"（{len(attachment_items)} 个附件已解析）" if attachment_items else "（无附件）"
        await sse_manager.send_progress(task_id, 1, 6, f"步骤1/6：提取公司信息...{att_summary}")
        company_profile, usage = await extract(excel_row, attachment_items, ext_cfg)
        token_tracker.add_usage("extractor", usage)
        company_name = company_profile.get("company_name", "未知公司")
        await sse_manager.send_progress(task_id, 1, 6, f"步骤1完成：已提取 {company_name} 的结构化信息")

        # ── Step 2: Research ─────────────────────────────────────────
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=2)
        await sse_manager.send_progress(task_id, 2, 6, "步骤2/6：联网研究中...")

        async def on_research_progress(msg: str):
            await sse_manager.send_progress(task_id, 2, 6, msg)

        research_data, usage = await research(company_profile, res_cfg, on_progress=on_research_progress, tools_config=tools_cfg)
        token_tracker.add_usage("researcher", usage)
        await sse_manager.send_progress(task_id, 2, 6, "步骤2完成：联网研究已完成")

        # ── Step 3: Write ────────────────────────────────────────────
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=3)
        log.info(
            "Step 3 Writer: passing %d attachments: %s",
            len(attachment_items),
            [(name, len(text)) for name, text in attachment_items],
        )
        await sse_manager.send_progress(task_id, 3, 6, "步骤3/6：生成尽调报告...")

        # Stream report generation chunks to frontend
        async def on_stream_chunk(chunk: str):
            await sse_manager.send_stream_chunk(task_id, chunk)

        report_md, usage = await write_report(
            company_profile, research_data, wrt_cfg, attachment_items,
            on_stream_chunk=on_stream_chunk
        )
        token_tracker.add_usage("writer", usage)
        await sse_manager.send_progress(task_id, 3, 6, "步骤3完成：报告已生成")

        # ── Save report + metadata + intermediate results ─────────────
        report_id = task_id
        report_path = OUTPUT_DIR / f"{report_id}.md"
        report_path.write_text(report_md, encoding="utf-8")
        _save_metadata(
            report_id, excel_row, company_profile, report_md,
            owner=owner, attachments_info=attachments_info,
            is_regeneration=is_regeneration,
        )

        # Save intermediate results for debugging
        debug_dir = OUTPUT_DIR / f"{report_id}_debug"
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / "company_profile.json").write_text(
            json.dumps(company_profile, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (debug_dir / "research_data.json").write_text(
            json.dumps(research_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Save attachment info
        att_info = [{"filename": name, "text_length": len(text)} for name, text in attachment_items]
        (debug_dir / "attachments_info.json").write_text(
            json.dumps(att_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ── Step 4: Field extraction (optional, graceful failure) ──
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=4)
        if fe_cfg.get("api_key"):
            try:
                await sse_manager.send_progress(task_id, 4, 6, "步骤4/6：字段回填中...")
                meta_path = OUTPUT_DIR / f"{report_id}.json"
                current_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                updates = await extract_fields(current_meta, report_md, fe_cfg)
                if updates:
                    # Protect system fields and locked fields from being overwritten
                    protected_keys = {
                        "report_id", "status", "created_at", "file_size",
                        "bd_code", "company_name", "project_name",
                    }
                    locked_fields = set(current_meta.get("locked_fields", []))
                    applied = 0
                    for k, v in updates.items():
                        if k not in protected_keys and k not in locked_fields:
                            current_meta[k] = v
                            applied += 1
                    meta_path.write_text(
                        json.dumps(current_meta, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    await sse_manager.send_progress(
                        task_id, 4, 6, f"步骤4完成：已回填 {applied} 个字段"
                    )
                else:
                    await sse_manager.send_progress(
                        task_id, 4, 6, "步骤4完成：无需更新字段"
                    )
            except Exception as e:
                await sse_manager.send_progress(
                    task_id, 4, 6, f"步骤4：字段回填失败（不影响报告）: {e}"
                )
        else:
            await sse_manager.send_progress(
                task_id, 4, 6, "步骤4：字段回填已跳过（未配置API Key）"
            )

        # ── Step 5: Chunk & Index (optional, graceful failure) ──
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=5)
        try:
            await sse_manager.send_progress(task_id, 5, 6, "步骤5/6：生成报告分块与索引...")
            meta_path = OUTPUT_DIR / f"{report_id}.json"
            current_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            chunks = await chunk_and_index(report_md, current_meta, chk_cfg)
            chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
            chunks_path.write_text(
                json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            await sse_manager.send_progress(
                task_id, 5, 6,
                f"步骤5完成：已生成 {len(chunks)} 个分块"
                + (f"（含AI索引）" if chk_cfg.get("api_key") else "（无AI索引）"),
            )
        except Exception as e:
            await sse_manager.send_progress(
                task_id, 5, 6, f"步骤5：分块生成失败（不影响报告）: {e}"
            )

        # ── Step 6: FastGPT Push (optional, graceful failure) ──
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=6)
        fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}
        if fastgpt_cfg.get("enabled") and fastgpt_cfg.get("api_key"):
            chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
            if chunks_path.exists():
                try:
                    await sse_manager.send_progress(
                        task_id, 6, 6, "步骤6/6：推送到FastGPT知识库..."
                    )
                    chunks_data = json.loads(chunks_path.read_text(encoding="utf-8"))

                    # Load metadata to get bd_code and manual_rating
                    meta_path = OUTPUT_DIR / f"{report_id}.json"
                    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
                    bd_code = meta.get("bd_code", report_id[:8])
                    manual_rating = meta.get("manual_rating")
                    rating = meta.get("rating")
                    final_rating = manual_rating or rating

                    # Build collection name and tags
                    collection_name = f"{company_name}-{bd_code}"
                    tags = ["尽调报告", bd_code]
                    if final_rating:
                        tags.append(final_rating)

                    # Delete old collection if exists
                    dataset_id = fastgpt_cfg.get("dataset_id", "")
                    push_records = meta.get("push_records", {})
                    old_record = push_records.get(dataset_id)
                    if old_record and old_record.get("collection_id"):
                        await delete_collection(old_record["collection_id"], fastgpt_cfg)

                    # Push new collection with tags
                    result = await push_chunks_to_fastgpt(
                        chunks_data, collection_name, fastgpt_cfg, tags=tags
                    )

                    # Save push record
                    save_push_record(
                        report_id, dataset_id,
                        result["collection_id"], result["uploaded"], result["total"],
                    )
                    await sse_manager.send_progress(
                        task_id, 6, 6,
                        f"步骤6完成：已推送 {result['uploaded']}/{result['total']} 条到FastGPT"
                    )
                except Exception as e:
                    await sse_manager.send_progress(
                        task_id, 6, 6, f"步骤6：FastGPT推送失败（不影响报告）: {e}"
                    )
            else:
                await sse_manager.send_progress(
                    task_id, 6, 6, "步骤6：无分块数据，跳过FastGPT推送"
                )
        else:
            await sse_manager.send_progress(
                task_id, 6, 6, "步骤6：FastGPT推送已跳过（未启用或未配置）"
            )

        await sse_manager.send_complete(task_id, report_id)
        await task_manager.update_task_status(task_id, TaskStatus.COMPLETED)

    except Exception as e:
        tb = traceback.format_exc()
        await sse_manager.send_error(task_id, f"{e}\n{tb}")
        await task_manager.update_task_status(task_id, TaskStatus.FAILED, error_message=str(e))
