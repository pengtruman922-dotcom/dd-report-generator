"""Light-update pipeline: Step3' (rewrite with changed fields) + Step4 + Step5 + Step6.

Skips Step1 (extraction) and Step2 (research) for fast field-level updates.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from typing import Any

from config import OUTPUT_DIR, load_settings, DEFAULT_FASTGPT_CONFIG
from parsers.excel_parser import FIELD_LABELS
from services.sse_manager import sse_manager
from services.task_manager import task_manager, TaskStatus
from services.token_tracker import TokenTracker

log = logging.getLogger(__name__)


def _format_changed_fields(changed_fields: dict) -> str:
    """Format changed fields for the writer prompt."""
    lines = []
    for field_key, change in changed_fields.items():
        label = FIELD_LABELS.get(field_key, field_key)
        if isinstance(change, dict):
            old_val = change.get("old") or "（原无）"
            new_val = change.get("new") or "（空）"
            lines.append(f"- {label}：{old_val} → {new_val}")
        else:
            lines.append(f"- {label}：{change}")
    return "\n".join(lines)


async def run_light_update_pipeline(
    task_id: str,
    report_id: str,
    changed_fields: dict[str, Any],
    owner: str | None = None,
    research_age_days: int | None = None,
):
    """
    Light-update pipeline for existing reports.

    Steps:
        Step3' – Rewrite report based on changed fields
        Step4  – Field backfill
        Step5  – Re-chunk and re-index
        Step6  – FastGPT re-push
    """
    settings = load_settings()
    ai = settings.get("ai_config", {})
    wrt_cfg = ai.get("writer", {})
    fe_cfg = ai.get("field_extractor", {})
    chk_cfg = ai.get("chunker", {})
    if not chk_cfg.get("api_key"):
        chk_cfg = {**chk_cfg,
                   "api_key": ai.get("extractor", {}).get("api_key", ""),
                   "base_url": chk_cfg.get("base_url") or ai.get("extractor", {}).get("base_url", ""),
                   "model": chk_cfg.get("model") or ai.get("extractor", {}).get("model", "")}

    token_tracker = TokenTracker()

    try:
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=0)

        # Validate writer config
        if not wrt_cfg.get("api_key"):
            await sse_manager.send_error(task_id, "请先配置 Writer 的 API Key，然后重试。")
            return

        # Load existing report
        md_path = OUTPUT_DIR / f"{report_id}.md"
        meta_path = OUTPUT_DIR / f"{report_id}.json"

        if not md_path.exists():
            await sse_manager.send_error(task_id, f"报告文件不存在：{report_id}.md")
            return

        original_report = md_path.read_text(encoding="utf-8")
        current_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        company_name = current_meta.get("company_name", "未知公司")

        # Create version backup before update
        try:
            from services.version_manager import create_version
            create_version(report_id, reason="before_light_update", created_by=owner)
        except Exception as e:
            log.warning("Failed to create version backup before light update: %s", e)

        # ── Step 3': Rewrite report with changed fields ───────────────────
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=1)

        age_notice = ""
        if research_age_days is not None:
            age_notice = f"\n\n注意：联网调研数据来自 {research_age_days} 天前，本次更新沿用该数据，仅更新以下变化字段。"

        changed_summary = _format_changed_fields(changed_fields)
        await sse_manager.send_progress(
            task_id, 1, 3,
            f"步骤1/3：根据字段变化更新报告内容...（沿用调研数据）"
        )

        update_prompt = (
            f"以下字段已更新：\n{changed_summary}{age_notice}\n\n"
            f"原报告全文如下：\n{original_report}\n\n"
            f"请基于上述字段变化，更新报告中所有受影响的段落（包括但不限于相关分析段落、"
            f"评分结论、核心摘要等），其余段落保持原文不变，输出完整报告。"
        )

        from agents.base_agent import create_client, chat_completion_stream
        client = create_client(wrt_cfg.get("base_url", ""), wrt_cfg.get("api_key", ""))
        model = wrt_cfg.get("model", "qwen3-max")

        report_chunks: list[str] = []

        async def on_stream_chunk(chunk: str):
            await sse_manager.send_stream_chunk(task_id, chunk)
            report_chunks.append(chunk)

        async for chunk in chat_completion_stream(
            client, model,
            messages=[{"role": "user", "content": update_prompt}],
        ):
            await on_stream_chunk(chunk)

        new_report_md = "".join(report_chunks)
        if not new_report_md.strip():
            await sse_manager.send_error(task_id, "报告更新失败：LLM 返回了空内容")
            return

        # Estimate token usage (streaming doesn't return usage)
        estimated_tokens = len(update_prompt) // 4 + len(new_report_md) // 4
        token_tracker.add_usage("writer", {
            "prompt_tokens": len(update_prompt) // 4,
            "completion_tokens": len(new_report_md) // 4,
            "total_tokens": estimated_tokens,
        })

        # Save updated report
        md_path.write_text(new_report_md, encoding="utf-8")

        # Update metadata with changed field values and new file_size/updated_at
        for field_key, change in changed_fields.items():
            new_val = change.get("new") if isinstance(change, dict) else change
            if new_val is not None and field_key not in current_meta.get("locked_fields", []):
                current_meta[field_key] = new_val
        current_meta["updated_at"] = datetime.now().isoformat()
        current_meta["file_size"] = len(new_report_md.encode("utf-8"))
        current_meta["status"] = "updated"

        # Re-extract score from updated report
        import re as _re
        m = _re.search(r"综合得分.*?\*\*\s*([\d.]+)\s*\*\*", new_report_md)
        if m:
            score = float(m.group(1))
            current_meta["score"] = score
            if score >= 8.0:
                current_meta["rating"] = "强烈推荐"
            elif score >= 6.5:
                current_meta["rating"] = "推荐"
            elif score >= 5.0:
                current_meta["rating"] = "谨慎推荐"
            elif score >= 3.5:
                current_meta["rating"] = "不推荐"
            else:
                current_meta["rating"] = "不建议"

        meta_path.write_text(json.dumps(current_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # Sync to DB
        _sync_meta_to_db(report_id, current_meta)

        await sse_manager.send_progress(task_id, 1, 3, "步骤1/3完成：报告内容已更新")

        # ── Step 4: Field backfill (optional) ────────────────────────────
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=2)
        if fe_cfg.get("api_key"):
            try:
                await sse_manager.send_progress(task_id, 2, 3, "步骤2/3：字段回填中...")
                from agents.field_extractor import extract_fields
                updates, usage = await extract_fields(current_meta, new_report_md, fe_cfg)
                token_tracker.add_usage("field_extractor", usage)
                if updates:
                    protected = {"report_id", "status", "created_at", "bd_code", "company_name", "project_name"}
                    locked = set(current_meta.get("locked_fields", []))
                    applied = 0
                    for k, v in updates.items():
                        if k not in protected and k not in locked:
                            current_meta[k] = v
                            applied += 1
                    meta_path.write_text(json.dumps(current_meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    _sync_meta_to_db(report_id, current_meta)
                    await sse_manager.send_progress(task_id, 2, 3, f"步骤2/3完成：已回填 {applied} 个字段")
                else:
                    await sse_manager.send_progress(task_id, 2, 3, "步骤2/3完成：无需更新字段")
            except Exception as e:
                await sse_manager.send_progress(task_id, 2, 3, f"步骤2/3：字段回填失败（不影响报告）: {e}")
        else:
            await sse_manager.send_progress(task_id, 2, 3, "步骤2/3：字段回填已跳过（未配置API Key）")

        # ── Step 5: Re-chunk & re-index ───────────────────────────────────
        await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=3)
        try:
            await sse_manager.send_progress(task_id, 3, 3, "步骤3/3：重新生成分块与索引...")
            from services.chunker import chunk_and_index
            chunks = await chunk_and_index(new_report_md, current_meta, chk_cfg)
            chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
            chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
            await sse_manager.send_progress(task_id, 3, 3, f"步骤3/3分块完成：{len(chunks)} 个分块")
        except Exception as e:
            await sse_manager.send_progress(task_id, 3, 3, f"步骤3/3：分块失败（不影响报告）: {e}")

        # ── Step 6: FastGPT re-push (optional) ───────────────────────────
        fastgpt_cfg = {**DEFAULT_FASTGPT_CONFIG, **settings.get("fastgpt", {})}
        if fastgpt_cfg.get("enabled") and fastgpt_cfg.get("api_key"):
            chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
            if chunks_path.exists():
                try:
                    from services.fastgpt_uploader import push_chunks_to_fastgpt, delete_collection, save_push_record
                    chunks_data = json.loads(chunks_path.read_text(encoding="utf-8"))
                    bd_code = current_meta.get("bd_code", report_id[:8])
                    final_rating = current_meta.get("manual_rating") or current_meta.get("rating")
                    collection_name = f"{company_name}-{bd_code}"
                    tags = ["尽调报告", bd_code]
                    if final_rating:
                        tags.append(final_rating)

                    dataset_id = fastgpt_cfg.get("dataset_id", "")
                    push_records = current_meta.get("push_records", {})
                    old_record = push_records.get(dataset_id)
                    if old_record and old_record.get("collection_id"):
                        await delete_collection(old_record["collection_id"], fastgpt_cfg)

                    result = await push_chunks_to_fastgpt(chunks_data, collection_name, fastgpt_cfg, tags=tags)
                    save_push_record(report_id, dataset_id, result["collection_id"],
                                     result["uploaded"], result["total"])
                    await sse_manager.send_progress(
                        task_id, 3, 3,
                        f"已推送 {result['uploaded']}/{result['total']} 条到FastGPT"
                    )
                except Exception as e:
                    log.warning("FastGPT re-push failed: %s", e)

        await sse_manager.send_complete(task_id, report_id)
        await task_manager.update_task_status(task_id, TaskStatus.COMPLETED)

    except Exception as e:
        tb = traceback.format_exc()
        await sse_manager.send_error(task_id, f"{e}\n{tb}")
        await task_manager.update_task_status(task_id, TaskStatus.FAILED, error_message=str(e))


def _sync_meta_to_db(report_id: str, meta: dict) -> None:
    """Sync a subset of metadata fields to the reports SQLite table."""
    from db import get_db
    updatable_cols = {
        "company_name", "project_name", "industry", "province", "city", "district",
        "is_listed", "stock_code", "website", "revenue", "net_profit",
        "revenue_yuan", "net_profit_yuan", "valuation_yuan", "valuation_date",
        "description", "company_intro", "industry_tags", "referral_status",
        "is_traded", "dept_primary", "dept_owner", "remarks",
        "score", "rating", "status", "file_size", "updated_at",
    }
    updates = {k: v for k, v in meta.items() if k in updatable_cols}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [report_id]
    try:
        conn = get_db()
        conn.execute(f"UPDATE reports SET {set_clause} WHERE report_id = ?", values)
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("light_update DB sync failed: %s", e)
