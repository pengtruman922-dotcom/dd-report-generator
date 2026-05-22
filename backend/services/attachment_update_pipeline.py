"""Attachment-driven v4 update pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable
from datetime import datetime

from openai import AsyncOpenAI

from config import OUTPUT_DIR
from db import get_db
from services.attachment_text_cache import load_parsed_attachment_text, persist_parsed_attachment_texts
from services.index_builder import build_index_bundle
from services.pipeline_v3 import (
    _coerce_to_v4_chunk_state,
    _collect_attachment_metadata,
    _first_usable_ai_config,
    _get_current_rating,
    _hash_chunk_state,
    _hash_json_value,
    _has_static_fact_updates,
    _load_existing_chunks,
    _load_report_metadata_json,
    _maybe_auto_push_to_fastgpt,
    _merge_chunk_state,
    _save_rating,
    _save_report_v3,
    _select_pushable_chunks_state,
)
from utils.file_parser import parse_attachment

log = logging.getLogger(__name__)
_ATTACHMENT_TEXT_LIMIT = 100_000


async def run_attachment_update_pipeline(
    report_id: str,
    attachment_filenames: list[str],
    settings: dict,
    owner: str | None = None,
    user_note: str | None = None,
    on_progress: Callable[[int, int, str], Any] | None = None,
) -> dict[str, Any]:
    """Update an existing report using newly uploaded attachments."""
    report = _load_report_meta(report_id)
    if not report:
        raise ValueError(f"Report not found: {report_id}")

    existing_chunks = _coerce_to_v4_chunk_state(_load_existing_chunks(report_id) or {})
    existing_metadata = _load_report_metadata_json(report_id)
    existing_snapshot = existing_metadata.get("seller_fact_snapshot_json") or {}
    total_steps = 5 if (settings.get("fastgpt", {}) or {}).get("enabled") else 4

    await _emit_progress(on_progress, 1, total_steps, "Step 1/5: 解析新附件...")
    parsed_attachments = _parse_selected_attachments(report_id, attachment_filenames)
    persist_parsed_attachment_texts(
        report_id,
        {
            item["filename"]: item.get("text", "")
            for item in parsed_attachments
            if item.get("text")
        },
    )
    attachment_summaries = {
        item["filename"]: item.get("text", "")[:_ATTACHMENT_TEXT_LIMIT]
        for item in parsed_attachments
        if item.get("text")
    }
    material_summary = _build_attachment_material_summary(parsed_attachments, user_note)

    await _emit_progress(on_progress, 2, total_steps, "Step 2/5: Tracking Processor 处理中...")
    ai_config = settings.get("ai_config", {})
    tracking_ai_config = _first_usable_ai_config(
        ai_config.get("tracking_processor"),
        ai_config.get("writer_agent"),
        ai_config.get("researcher"),
    )
    info_ai_config = _first_usable_ai_config(
        ai_config.get("info_chunk_writer"),
        ai_config.get("writer_agent"),
        ai_config.get("researcher"),
    )

    from agents.tracking_processor import process_tracking
    from agents.info_chunk_writer import write_info_chunk
    from agents.rating_agent import run_rating_agent

    tracking_result = await process_tracking(
        company_profile=_planner_company_profile(report),
        material_summary=(user_note or "").strip(),
        attachment_summaries={},
        existing_tracking_chunk=existing_chunks.get("tracking"),
        existing_snapshot=existing_snapshot,
        ai_config=tracking_ai_config,
        current_system_time=datetime.now().isoformat(timespec="seconds"),
    )
    snapshot = tracking_result.get("seller_fact_snapshot") or {}
    snapshot_changed = _hash_json_value(snapshot) != _hash_json_value(existing_snapshot)

    updated_chunks: dict[str, dict[str, Any]] = {
        "tracking": {
            **(tracking_result.get("tracking_chunk") or {}),
            "extracted_fields": tracking_result.get("extracted_fields") or {},
        }
    }

    should_update_info = (
        "info" not in existing_chunks
        or snapshot_changed
        or _attachments_have_static_facts(parsed_attachments)
    )

    if should_update_info:
        await _emit_progress(on_progress, 3, total_steps, "Step 3/5: Info Chunk Writer 生成中...")
        updated_chunks["info"] = await write_info_chunk(
            company_profile=_planner_company_profile(report),
            material_summary=material_summary,
            attachment_summaries=attachment_summaries,
            research_data=None,
            seller_fact_snapshot=snapshot,
            existing_info_chunk=existing_chunks.get("info"),
            ai_config=info_ai_config,
        )
    else:
        await _emit_progress(on_progress, 3, total_steps, "Step 3/5: 跳过 info_chunk 重写（当前有效事实未变化）")

    current_chunk_state = _merge_chunk_state(existing_chunks, updated_chunks)
    index_bundle = build_index_bundle(
        company_name=report.get("company_name", ""),
        bd_code=report.get("bd_code", ""),
        info_chunk=current_chunk_state.get("info"),
        tracking_chunk=current_chunk_state.get("tracking"),
    )
    if current_chunk_state.get("info"):
        if index_bundle.get("info_summary"):
            current_chunk_state["info"]["summary"] = index_bundle["info_summary"]
        current_chunk_state["info"]["index_tags"] = index_bundle.get("info_index_tags", [])
    if current_chunk_state.get("tracking") and index_bundle.get("tracking_summary"):
        current_chunk_state["tracking"]["summary"] = index_bundle["tracking_summary"]

    await _emit_progress(on_progress, 4, total_steps, "Step 4/5: 保存更新内容...")
    previous_chunk_hash = _hash_chunk_state(_select_pushable_chunks_state(existing_chunks))
    current_chunk_hash = _hash_chunk_state(_select_pushable_chunks_state(current_chunk_state))

    merged_fields = {
        **report,
        **{k: v for chunk in current_chunk_state.values() for k, v in (chunk.get("extracted_fields") or {}).items() if v is not None},
    }
    merged_fields["company_name"] = report.get("company_name", "")
    merged_fields["bd_code"] = report.get("bd_code", "")

    backfilled_fields = _save_report_v3(
        report_id=report_id,
        bd_code=report.get("bd_code", ""),
        fields=merged_fields,
        chunks=current_chunk_state,
        action="update",
        owner=owner,
        attachments_info=_collect_attachment_metadata(report_id, None),
        metadata={
            "report_schema_version": "v4",
            "seller_fact_snapshot_json": snapshot,
            "tracking_summary": index_bundle.get("tracking_summary"),
            "info_summary": index_bundle.get("info_summary"),
            "info_index_tags": index_bundle.get("info_index_tags", []),
            "parsed_attachment_manifest": f"{report_id}_parsed_attachments/manifest.json",
            "excluded_context": tracking_result.get("excluded_context") or [],
        },
    )

    rating_result = None
    rating_cfg = ai_config.get("rating_agent") or info_ai_config
    if updated_chunks:
        await _emit_progress(on_progress, min(total_steps, 4), total_steps, "Step 4/5: 评级中...")
        client = AsyncOpenAI(
            base_url=rating_cfg.get("base_url", ""),
            api_key=rating_cfg.get("api_key", ""),
        )
        model = rating_cfg.get("model", "qwen3-max")
        rating_result = await run_rating_agent(
            chunks={
                chunk_id: {
                    "summary": chunk.get("summary", ""),
                    "content": chunk.get("content", ""),
                }
                for chunk_id, chunk in current_chunk_state.items()
            },
            current_rating=_get_current_rating(report_id),
            action="update",
            client=client,
            model=model,
        )
        _save_rating(report_id, rating_result, "update")

    push_step = 5 if total_steps >= 5 else total_steps
    push_message = "Step 5/5: 推送中..." if total_steps >= 5 else "Step 4/4: 推送中..."
    await _emit_progress(on_progress, push_step, total_steps, push_message)
    auto_push_result = await _maybe_auto_push_to_fastgpt(
        report_id=report_id,
        action="update",
        current_chunk_state=_select_pushable_chunks_state(current_chunk_state) or {},
        previous_chunk_hash=previous_chunk_hash,
        current_chunk_hash=current_chunk_hash,
        settings=settings,
        on_progress=lambda msg: _emit_progress(on_progress, push_step, total_steps, msg),
    )

    final_message = f"附件更新完成，已更新 {len(updated_chunks)} 个产物"
    await _emit_progress(on_progress, total_steps, total_steps, final_message)

    return {
        "report_id": report_id,
        "bd_code": report.get("bd_code"),
        "updated_chunks": list(updated_chunks.keys()),
        "backfilled_fields": backfilled_fields,
        "rating": rating_result.get("rating") if rating_result else None,
        "auto_push": auto_push_result,
        "attachments_used": [item["filename"] for item in parsed_attachments],
        "affected_chunks": list(updated_chunks.keys()),
        "steps_skipped": [] if should_update_info else [{"step": "info_chunk", "reason": "snapshot 未变化"}],
    }


async def _emit_progress(
    on_progress: Callable[[int, int, str], Any] | None,
    step: int,
    total: int,
    message: str,
) -> None:
    if not on_progress:
        return
    result = on_progress(step, total, message)
    if hasattr(result, "__await__"):
        await result


def _load_report_meta(report_id: str) -> dict[str, Any] | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _parse_selected_attachments(report_id: str, attachment_filenames: list[str]) -> list[dict[str, Any]]:
    att_dir = OUTPUT_DIR / f"{report_id}_attachments"
    parsed_items: list[dict[str, Any]] = []
    for filename in attachment_filenames:
        cached_text = load_parsed_attachment_text(report_id, filename)
        if cached_text:
            parsed_items.append({
                "filename": Path(filename).name,
                "file_type": Path(filename).suffix.lower().lstrip("."),
                "text": cached_text[:_ATTACHMENT_TEXT_LIMIT],
                "error": None,
            })
            continue

        fp = att_dir / Path(filename).name
        if not fp.exists() or not fp.is_file():
            raise FileNotFoundError(f"Attachment not found: {filename}")
        parsed = parse_attachment(fp)
        text = (parsed.get("text") or "").strip()
        parsed_items.append({
            "filename": parsed.get("filename", fp.name),
            "file_type": parsed.get("file_type", fp.suffix.lower().lstrip(".")),
            "text": text[:_ATTACHMENT_TEXT_LIMIT],
            "error": parsed.get("error"),
        })
    return parsed_items


def _planner_company_profile(report: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "report_id",
        "bd_code",
        "company_name",
        "project_name",
        "industry",
        "stock_code",
        "is_listed",
        "website",
        "province",
        "city",
        "district",
        "feasibility_rating",
    ]
    return {key: report.get(key) for key in keys if report.get(key) is not None}


def _build_attachment_material_summary(
    parsed_attachments: list[dict[str, Any]],
    user_note: str | None,
) -> str:
    parts: list[str] = []
    if user_note and user_note.strip():
        parts.append(f"用户备注：{user_note.strip()}")
    for item in parsed_attachments:
        text = (item.get("text") or "").strip()
        if text:
            parts.append(f"附件 {item['filename']}：{text[:1500]}")
        elif item.get("error"):
            parts.append(f"附件 {item['filename']} 解析失败：{item['error']}")
    return "\n\n".join(parts)


def _attachments_have_static_facts(parsed_attachments: list[dict[str, Any]]) -> bool:
    keywords = ("营收", "净利润", "融资", "股权", "产品", "客户", "供应商", "行业", "处罚", "诉讼")
    for item in parsed_attachments:
        text = item.get("text") or ""
        if any(keyword in text for keyword in keywords):
            return True
    return False
