"""v4 pipeline running behind the legacy pipeline_v3 entrypoint."""

from __future__ import annotations

import json
import logging
import hashlib
from datetime import datetime
from typing import Any, Callable

from openai import AsyncOpenAI

from config import OUTPUT_DIR
from db import get_db
from services.fastgpt_uploader import push_report_to_fastgpt
from services.index_builder import build_index_bundle
from services.attachment_text_cache import load_parsed_attachment_text, persist_parsed_attachment_texts
from utils.attachment_manager import get_attachment_path
from utils.file_parser import parse_attachment

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
_ALL_CHUNK_LABELS = {**_V3_CHUNK_LABELS, **_V4_CHUNK_LABELS}

_AUTO_BACKFILL_FIELDS = [
    "company_name",
    "project_name",
    "is_listed",
    "stock_code",
    "province",
    "city",
    "district",
    "website",
    "revenue",
    "net_profit",
    "revenue_yuan",
    "net_profit_yuan",
    "description",
    "company_intro",
    "industry",
    "industry_tags",
    "valuation_yuan",
    "valuation_date",
    "offer_yuan",
    "offer_date",
    "is_traded",
    "referral_status",
]
_RESEARCH_TRIGGER_FIELDS = {
    "company_name",
    "project_name",
    "industry",
    "is_listed",
    "stock_code",
    "website",
    "description",
    "company_intro",
    "revenue",
    "net_profit",
    "valuation_yuan",
    "offer_yuan",
}
_RESEARCH_HINT_KEYWORDS = (
    "营收", "收入", "净利润", "融资", "股权", "官网", "处罚", "诉讼",
    "上市", "产品", "客户", "供应商", "赛道", "行业",
)
_ATTACHMENT_TEXT_LIMIT = 100_000


def _has_usable_ai_config(config: dict[str, Any] | None) -> bool:
    if not config:
        return False
    return bool(str(config.get("api_key") or "").strip() and str(config.get("base_url") or "").strip())


def _first_usable_ai_config(*configs: dict[str, Any] | None) -> dict[str, Any]:
    for config in configs:
        if _has_usable_ai_config(config):
            return config or {}
    return {}


async def run_pipeline_v3(
    task_id: str,
    action: str,
    company_name: str,
    bd_code: str,
    fields: dict,
    material_summary: str,
    attachment_filenames: list[str],
    attachments_info: list[dict[str, Any]] | None,
    settings: dict,
    owner: str | None = None,
    on_progress: Callable | None = None,
    parsed_attachment_texts: dict[str, str] | None = None,
    tracking_material_summary: str | None = None,
) -> dict:
    """Run the v4 pipeline through the legacy public entrypoint."""
    ai_config = settings.get("ai_config", {})
    tools_config = settings.get("tools", {})

    researcher_ai_config = _first_usable_ai_config(
        ai_config.get("researcher"),
        ai_config.get("info_chunk_writer"),
        ai_config.get("tracking_processor"),
        ai_config.get("writer_agent"),
    )
    tracking_ai_config = _first_usable_ai_config(
        ai_config.get("tracking_processor"),
        ai_config.get("writer_agent"),
        researcher_ai_config,
    )
    info_ai_config = _first_usable_ai_config(
        ai_config.get("info_chunk_writer"),
        ai_config.get("writer_agent"),
        researcher_ai_config,
    )
    rating_ai_config = _first_usable_ai_config(ai_config.get("rating_agent"), info_ai_config)
    client = AsyncOpenAI(
        base_url=rating_ai_config.get("base_url", ""),
        api_key=rating_ai_config.get("api_key", ""),
    )
    model = rating_ai_config.get("model", "qwen3-max")

    report_id = task_id if action == "create" else _get_report_id(bd_code)
    if not report_id:
        raise ValueError(f"Cannot find report_id for bd_code={bd_code}")

    company_profile = {
        "company_name": company_name,
        "report_id": report_id,
        **{k: v for k, v in fields.items() if v is not None},
    }

    existing_chunks = _load_existing_chunks(report_id) if action == "update" else None
    existing_metadata = _load_report_metadata_json(report_id) if action == "update" else {}
    existing_snapshot = (existing_metadata or {}).get("seller_fact_snapshot_json") or {}
    existing_v4_chunks = _coerce_to_v4_chunk_state(existing_chunks)

    attachment_summaries = _load_attachment_summaries(
        report_id,
        attachment_filenames,
        parsed_attachment_texts=parsed_attachment_texts,
    )
    should_run_research = _should_run_research(
        action=action,
        fields=fields,
        material_summary=material_summary,
        existing_chunks=existing_v4_chunks,
    )

    if on_progress:
        await _maybe_await(on_progress, "Step 1/4: 事实链路规划中...")

    research_data = None
    research_usage = None
    if should_run_research:
        if on_progress:
            await _maybe_await(on_progress, "正在调研公开事实...")
        from agents.researcher import research

        research_data, research_usage = await research(
            company_profile=company_profile,
            ai_config=researcher_ai_config,
            tools_config=tools_config,
            on_progress=on_progress,
        )
        if on_progress:
            await _maybe_await(on_progress, "Research 完成")
    elif on_progress:
        await _maybe_await(on_progress, "Research 已跳过：未识别到公开事实缺口")

    if on_progress:
        await _maybe_await(on_progress, "Step 1 完成: 事实输入已就绪")

    if on_progress:
        await _maybe_await(on_progress, "Step 2/4: Tracking Processor 处理中...")

    from agents.tracking_processor import process_tracking

    tracking_result = await process_tracking(
        company_profile=company_profile,
        material_summary=tracking_material_summary if tracking_material_summary is not None else material_summary,
        attachment_summaries={},
        existing_tracking_chunk=existing_v4_chunks.get("tracking"),
        existing_snapshot=existing_snapshot,
        ai_config=tracking_ai_config,
        current_system_time=datetime.now().isoformat(timespec="seconds"),
    )
    snapshot = tracking_result.get("seller_fact_snapshot") or {}
    snapshot_changed = _hash_json_value(snapshot) != _hash_json_value(existing_snapshot)

    chunks_written: list[str] = []
    updated_chunks: dict[str, dict[str, Any]] = {
        "tracking": {
            **(tracking_result.get("tracking_chunk") or {}),
            "extracted_fields": tracking_result.get("extracted_fields") or {},
        }
    }
    chunks_written.append("tracking")

    should_update_info = (
        action == "create"
        or "info" not in existing_v4_chunks
        or snapshot_changed
        or _has_static_fact_updates(fields)
        or should_run_research
    )

    if should_update_info:
        if on_progress:
            await _maybe_await(on_progress, "Step 2/4: Info Chunk Writer 生成中...")

        from agents.info_chunk_writer import write_info_chunk

        updated_chunks["info"] = await write_info_chunk(
            company_profile=company_profile,
            material_summary=material_summary,
            attachment_summaries=attachment_summaries,
            research_data=research_data,
            seller_fact_snapshot=snapshot,
            existing_info_chunk=existing_v4_chunks.get("info"),
            ai_config=info_ai_config,
        )
        chunks_written.append("info")
    elif on_progress:
        await _maybe_await(on_progress, "Info Chunk 已跳过：当前有效事实未变化")

    if on_progress:
        await _maybe_await(on_progress, f"Step 2 完成: 更新了 {len(chunks_written)} 个产物")

    if on_progress:
        await _maybe_await(on_progress, "Step 3/4: 保存数据...")

    current_chunk_state = _merge_chunk_state(existing_v4_chunks, updated_chunks)
    index_bundle = build_index_bundle(
        company_name=company_name,
        bd_code=bd_code,
        info_chunk=current_chunk_state.get("info"),
        tracking_chunk=current_chunk_state.get("tracking"),
    )
    if current_chunk_state.get("info"):
        if index_bundle.get("info_summary"):
            current_chunk_state["info"]["summary"] = index_bundle["info_summary"]
        current_chunk_state["info"]["index_tags"] = index_bundle.get("info_index_tags", [])
    if current_chunk_state.get("tracking") and index_bundle.get("tracking_summary"):
        current_chunk_state["tracking"]["summary"] = index_bundle["tracking_summary"]

    all_extracted, _ = _extract_fields_from_chunks(current_chunk_state)
    merged_fields = {**all_extracted, **fields}
    merged_fields["company_name"] = company_name
    merged_fields["bd_code"] = bd_code

    previous_chunk_hash = (
        _hash_chunk_state(_select_pushable_chunks_state(existing_v4_chunks)) if action == "update" else None
    )
    current_chunk_hash = _hash_chunk_state(_select_pushable_chunks_state(current_chunk_state))

    backfilled_fields = _save_report_v3(
        report_id,
        bd_code,
        merged_fields,
        current_chunk_state,
        action,
        owner,
        attachments_info=attachments_info,
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

    if research_data:
        _save_research_data(report_id, research_data)

    if on_progress:
        await _maybe_await(on_progress, "Step 3 完成: 数据已保存")

    rating_result = None
    if _should_run_rating(action, updated_chunks, fields):
        if on_progress:
            await _maybe_await(on_progress, "Step 4/4: 评级中...")

        from agents.rating_agent import run_rating_agent, should_rate_on_create, should_rate_on_update

        if action == "create":
            should_rate, _ = should_rate_on_create({"text": material_summary})
        else:
            current_rating = _get_current_rating(report_id)
            should_rate, _ = should_rate_on_update(
                {"text": material_summary}, current_rating, list(updated_chunks.keys())
            )

        if should_rate:
            rating_chunks = {
                chunk_id: {
                    "summary": chunk_data.get("summary", ""),
                    "content": chunk_data.get("content", ""),
                }
                for chunk_id, chunk_data in current_chunk_state.items()
            }
            current_rating = _get_current_rating(report_id) if action == "update" else None
            rating_result = await run_rating_agent(
                chunks=rating_chunks,
                current_rating=current_rating,
                action=action,
                client=client,
                model=model,
            )
            _save_rating(report_id, rating_result, action)
            if on_progress:
                await _maybe_await(
                    on_progress,
                    f"Step 4 完成: 评级 {rating_result.get('rating', 'N/A')}",
                )
    elif on_progress:
        await _maybe_await(on_progress, "Step 4/4: 跳过评级")

    auto_push_result = await _maybe_auto_push_to_fastgpt(
        report_id=report_id,
        action=action,
        current_chunk_state=_select_pushable_chunks_state(current_chunk_state) or {},
        previous_chunk_hash=previous_chunk_hash,
        current_chunk_hash=current_chunk_hash,
        settings=settings,
        on_progress=on_progress,
    )

    return {
        "report_id": report_id,
        "bd_code": bd_code,
        "chunks_written": chunks_written,
        "backfilled_fields": backfilled_fields,
        "rating": rating_result.get("rating") if rating_result else None,
        "auto_push": auto_push_result,
        "research_usage": research_usage,
    }


def _get_report_id(bd_code: str) -> str | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT report_id FROM reports WHERE bd_code = ? ORDER BY created_at DESC LIMIT 1",
            (bd_code,),
        ).fetchone()
        return row["report_id"] if row else None
    finally:
        conn.close()


def _load_existing_chunks(report_id: str) -> dict[str, dict] | None:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT chunk_id, summary, content, index_tags FROM report_chunks WHERE report_id = ?",
            (report_id,),
        ).fetchall()
        if not rows:
            return None
        return {
            row["chunk_id"]: {
                "summary": row["summary"] or "",
                "content": row["content"] or "",
                "index_tags": json.loads(row["index_tags"]) if row["index_tags"] else [],
            }
            for row in rows
        }
    finally:
        conn.close()


def _load_report_metadata_json(report_id: str) -> dict[str, Any]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT metadata_json FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if not row or not row["metadata_json"]:
            return {}
        try:
            parsed = json.loads(row["metadata_json"])
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    finally:
        conn.close()


def _coerce_to_v4_chunk_state(existing_chunks: dict[str, dict] | None) -> dict[str, dict]:
    if not existing_chunks:
        return {}
    if "info" in existing_chunks or "tracking" in existing_chunks:
        return existing_chunks

    tracking = existing_chunks.get("chunk7")
    info_parts: list[str] = []
    info_tags: list[str] = []
    for chunk_id in ["chunk0", "chunk1", "chunk2", "chunk3", "chunk4", "chunk5", "chunk6"]:
        chunk = existing_chunks.get(chunk_id)
        if not chunk or not chunk.get("content"):
            continue
        info_parts.append(f"## {_ALL_CHUNK_LABELS.get(chunk_id, chunk_id)}\n\n{chunk['content']}")
        info_tags.extend(chunk.get("index_tags", []) or [])

    result: dict[str, dict] = {}
    if info_parts:
        result["info"] = {
            "summary": "",
            "content": "\n\n".join(info_parts),
            "index_tags": info_tags,
        }
    if tracking:
        result["tracking"] = tracking
    return result


def _merge_chunk_state(
    existing_chunks: dict[str, dict] | None,
    updated_chunks: dict[str, dict],
) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for source in (existing_chunks or {}, updated_chunks or {}):
        for chunk_id, chunk_data in source.items():
            merged[chunk_id] = {
                "summary": chunk_data.get("summary", "") or "",
                "content": chunk_data.get("content", "") or "",
                "index_tags": chunk_data.get("index_tags", []) or [],
                "extracted_fields": chunk_data.get("extracted_fields", {}) or {},
            }
    return merged


def _select_pushable_chunks_state(chunks: dict[str, dict] | None) -> dict[str, dict] | None:
    if not chunks:
        return None
    if "info" in chunks:
        return {"info": chunks["info"]}
    filtered = {key: value for key, value in chunks.items() if key not in {"tracking", "chunk7"}}
    return filtered or None


def _hash_chunk_state(chunks: dict[str, dict] | None) -> str | None:
    if not chunks:
        return None
    normalized = []
    for chunk_id in sorted(chunks.keys()):
        chunk = chunks[chunk_id] or {}
        normalized.append({
            "chunk_id": chunk_id,
            "summary": chunk.get("summary", "") or "",
            "content": chunk.get("content", "") or "",
            "index_tags": chunk.get("index_tags", []) or [],
        })
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _hash_json_value(value: Any) -> str | None:
    if value in (None, {}, []):
        return None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _extract_fields_from_chunks(
    chunks: dict[str, dict],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    merged_fields: dict[str, Any] = {}
    field_sources: dict[str, dict[str, str]] = {}
    for chunk_id, chunk_data in chunks.items():
        extracted = chunk_data.get("extracted_fields", {}) or {}
        for key, value in extracted.items():
            if value is None or not str(value).strip():
                continue
            merged_fields[key] = value
            field_sources[key] = {
                "chunk_id": chunk_id,
                "source_label": _ALL_CHUNK_LABELS.get(chunk_id, chunk_id),
            }
    return merged_fields, field_sources


def _load_report_field_snapshot(report_id: str) -> dict[str, Any]:
    conn = get_db()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_AUTO_BACKFILL_FIELDS)} FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def _normalized_compare_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _build_backfilled_field_changes(
    previous_values: dict[str, Any],
    new_values: dict[str, Any],
    field_sources: dict[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for field_name, source in field_sources.items():
        if field_name not in _AUTO_BACKFILL_FIELDS:
            continue
        new_value = new_values.get(field_name)
        if _normalized_compare_value(new_value) is None:
            continue
        old_value = previous_values.get(field_name)
        if _normalized_compare_value(old_value) == _normalized_compare_value(new_value):
            continue
        changes[field_name] = {
            "old": old_value,
            "new": new_value,
            "source_chunk": source["chunk_id"],
            "source_label": source["source_label"],
        }
    return changes


def _has_static_fact_updates(fields: dict[str, Any]) -> bool:
    return any(key in _RESEARCH_TRIGGER_FIELDS for key in fields.keys())


def _should_run_research(
    *,
    action: str,
    fields: dict[str, Any],
    material_summary: str,
    existing_chunks: dict[str, dict] | None,
) -> bool:
    if action == "create":
        return True
    if not existing_chunks or "info" not in existing_chunks:
        return True
    if _has_static_fact_updates(fields):
        return True
    return any(keyword in (material_summary or "") for keyword in _RESEARCH_HINT_KEYWORDS)


def _load_attachment_summaries(
    report_id: str,
    attachment_filenames: list[str],
    parsed_attachment_texts: dict[str, str] | None = None,
) -> dict[str, str]:
    summaries: dict[str, str] = {}
    for filename in attachment_filenames:
        pre_parsed = (parsed_attachment_texts or {}).get(filename)
        if pre_parsed and pre_parsed.strip():
            summaries[filename] = pre_parsed.strip()[:_ATTACHMENT_TEXT_LIMIT]
            continue
        cached_text = load_parsed_attachment_text(report_id, filename)
        if cached_text:
            summaries[filename] = cached_text[:_ATTACHMENT_TEXT_LIMIT]
            continue
        try:
            path = get_attachment_path(report_id, filename)
            if not path.exists():
                continue
            parsed = parse_attachment(path)
            text = (parsed.get("text") or "").strip()
            if text:
                summaries[filename] = text[:_ATTACHMENT_TEXT_LIMIT]
                persist_parsed_attachment_texts(report_id, {filename: text})
        except Exception as exc:
            log.warning("Failed to parse attachment %s for %s: %s", filename, report_id, exc)
    return summaries


async def _maybe_auto_push_to_fastgpt(
    report_id: str,
    action: str,
    current_chunk_state: dict[str, dict],
    previous_chunk_hash: str | None,
    current_chunk_hash: str | None,
    settings: dict,
    on_progress: Callable | None,
) -> dict[str, Any]:
    fastgpt_cfg = settings.get("fastgpt", {}) or {}
    if not fastgpt_cfg.get("enabled"):
        if on_progress:
            await _maybe_await(on_progress, "FastGPT 自动推送已跳过：未开启自动推送")
        return {"status": "skipped", "reason": "disabled"}

    if not current_chunk_state:
        if on_progress:
            await _maybe_await(on_progress, "FastGPT 自动推送已跳过：当前报告没有可推送的 chunks")
        return {"status": "skipped", "reason": "no_chunks"}

    should_push = action == "create" or previous_chunk_hash != current_chunk_hash
    if not should_push:
        if on_progress:
            await _maybe_await(on_progress, "FastGPT 自动推送已跳过：本次更新未检测到报告内容变化")
        return {
            "status": "skipped",
            "reason": "unchanged",
            "chunks_hash": current_chunk_hash,
        }

    if on_progress:
        if action == "create":
            await _maybe_await(on_progress, "FastGPT 自动推送中：新报告已生成，开始推送通用信息")
        else:
            await _maybe_await(on_progress, "FastGPT 自动推送中：检测到 info_chunk 变化，开始替换推送")

    try:
        result = await push_report_to_fastgpt(report_id, fastgpt_cfg, replace_existing=True)
        if on_progress:
            await _maybe_await(
                on_progress,
                f"FastGPT 自动推送完成：已上传 {result['uploaded']}/{result['total']} 个内容块",
            )
        return {
            "status": "pushed",
            "chunks_hash": current_chunk_hash,
            **result,
        }
    except Exception as e:
        log.exception("FastGPT auto-push failed for %s", report_id)
        if on_progress:
            await _maybe_await(on_progress, f"FastGPT 自动推送失败：{e}")
        return {
            "status": "failed",
            "reason": str(e),
            "chunks_hash": current_chunk_hash,
        }


def _save_report_v3(
    report_id: str,
    bd_code: str,
    fields: dict,
    chunks: dict,
    action: str,
    owner: str | None,
    attachments_info: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
 ) -> dict[str, dict[str, Any]]:
    """Save report metadata and chunks to database and return backfill details."""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        attachments_dir = str(OUTPUT_DIR / f"{report_id}_attachments")
        debug_dir = str(OUTPUT_DIR / f"{report_id}_debug")
        attachments_payload = _collect_attachment_metadata(report_id, attachments_info)
        attachments_json = json.dumps(attachments_payload, ensure_ascii=False)
        previous_values = _load_report_field_snapshot(report_id) if action == "update" else {}
        _, field_sources = _extract_fields_from_chunks(chunks)
        existing_metadata = _load_report_metadata_json(report_id) if action == "update" else {}
        merged_metadata = {**existing_metadata, **(metadata or {})}
        metadata_json = json.dumps(merged_metadata, ensure_ascii=False)

        if action == "create":
            conn.execute(
                """INSERT OR REPLACE INTO reports
                   (report_id, bd_code, company_name, project_name, industry,
                    province, city, district, is_listed, stock_code, website,
                    revenue, net_profit, revenue_yuan, net_profit_yuan,
                    valuation_yuan, valuation_date, description, company_intro,
                    industry_tags, referral_status, is_traded, offer_yuan,
                    offer_date, status, owner, created_at, updated_at,
                    report_format, attachments, attachments_dir, debug_dir, metadata_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report_id,
                    bd_code,
                    fields.get("company_name", ""),
                    fields.get("project_name", fields.get("company_name", "")),
                    fields.get("industry"),
                    fields.get("province"),
                    fields.get("city"),
                    fields.get("district"),
                    fields.get("is_listed"),
                    fields.get("stock_code"),
                    fields.get("website"),
                    fields.get("revenue"),
                    fields.get("net_profit"),
                    fields.get("revenue_yuan"),
                    fields.get("net_profit_yuan"),
                    fields.get("valuation_yuan"),
                    fields.get("valuation_date"),
                    fields.get("description"),
                    fields.get("company_intro"),
                    fields.get("industry_tags"),
                    fields.get("referral_status"),
                    fields.get("is_traded"),
                    fields.get("offer_yuan"),
                    fields.get("offer_date"),
                    "completed",
                    owner,
                    now,
                    now,
                    "v4",
                    attachments_json,
                    attachments_dir,
                    debug_dir,
                    metadata_json,
                ),
            )
        else:
            update_fields = []
            update_values = []
            for key in ["company_name", "project_name", "industry", "province", "city", "district",
                        "is_listed", "stock_code", "website",
                        "revenue", "net_profit", "revenue_yuan", "net_profit_yuan",
                        "description", "company_intro", "industry_tags",
                        "valuation_yuan", "valuation_date", "offer_yuan", "offer_date",
                        "is_traded", "referral_status"]:
                if key in fields and fields[key] is not None:
                    update_fields.append(f"{key} = ?")
                    update_values.append(fields[key])

            update_fields.append("updated_at = ?")
            update_values.append(now)
            update_fields.append("status = ?")
            update_values.append("updated")
            update_fields.append("report_format = ?")
            update_values.append("v4")
            update_fields.append("attachments = ?")
            update_values.append(attachments_json)
            update_fields.append("attachments_dir = ?")
            update_values.append(attachments_dir)
            update_fields.append("debug_dir = ?")
            update_values.append(debug_dir)
            update_fields.append("metadata_json = ?")
            update_values.append(metadata_json)
            update_values.append(report_id)

            conn.execute(
                f"UPDATE reports SET {', '.join(update_fields)} WHERE report_id = ?",
                update_values,
            )

        conn.execute("DELETE FROM report_chunks WHERE report_id = ?", (report_id,))
        for chunk_id, chunk_data in chunks.items():
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

        conn.commit()
        log.info("Saved v4 report %s with %d chunks", report_id, len(chunks))
        return _build_backfilled_field_changes(previous_values, fields, field_sources)

    finally:
        conn.close()


def _collect_attachment_metadata(
    report_id: str, attachments_info: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Collect attachment metadata from disk, falling back to provided info."""
    att_dir = OUTPUT_DIR / f"{report_id}_attachments"
    if att_dir.exists():
        files = []
        for fp in sorted(att_dir.iterdir()):
            if fp.is_file():
                files.append({"filename": fp.name, "size": fp.stat().st_size})
        if files:
            return files
    return attachments_info or []


def _save_research_data(report_id: str, research_data: dict):
    """Save research data to debug directory."""
    debug_dir = OUTPUT_DIR / f"{report_id}_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "research_data.json").write_text(
        json.dumps(research_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _should_run_rating(action: str, chunks: dict, fields: dict) -> bool:
    """Determine if rating should run."""
    if action == "create" and chunks:
        return True
    if action == "update":
        return bool({"info", "tracking", "chunk0", "chunk5", "chunk7"} & set(chunks.keys()))
    return False


def _get_current_rating(report_id: str) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT feasibility_rating, feasibility_rating_detail FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if row and row["feasibility_rating"]:
            detail = json.loads(row["feasibility_rating_detail"]) if row["feasibility_rating_detail"] else {}
            return {
                "rating": row["feasibility_rating"],
                **detail,
            }
        return None
    finally:
        conn.close()


def _save_rating(report_id: str, rating_result: dict, action: str):
    """Save rating to database."""
    conn = get_db()
    try:
        now = datetime.now().isoformat()

        if action == "create":
            conn.execute(
                """UPDATE reports SET
                   feasibility_rating = ?,
                   feasibility_rating_detail = ?,
                   feasibility_rating_at = ?
                   WHERE report_id = ?""",
                (
                    rating_result.get("rating"),
                    json.dumps(rating_result, ensure_ascii=False),
                    now,
                    report_id,
                ),
            )
        else:
            current = _get_current_rating(report_id)
            if current and current.get("rating") != rating_result.get("rating"):
                conn.execute(
                    """UPDATE reports SET
                       pending_rating_change = ?
                       WHERE report_id = ?""",
                    (json.dumps(rating_result, ensure_ascii=False), report_id),
                )
            else:
                conn.execute(
                    """UPDATE reports SET
                       feasibility_rating = ?,
                       feasibility_rating_detail = ?,
                       feasibility_rating_at = ?
                       WHERE report_id = ?""",
                    (
                        rating_result.get("rating"),
                        json.dumps(rating_result, ensure_ascii=False),
                        now,
                        report_id,
                    ),
                )

        conn.commit()
    finally:
        conn.close()


async def _maybe_await(fn, *args):
    import asyncio
    result = fn(*args)
    if asyncio.iscoroutine(result):
        await result
