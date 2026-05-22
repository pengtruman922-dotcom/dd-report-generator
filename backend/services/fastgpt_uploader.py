"""FastGPT knowledge base uploader — push report chunks to FastGPT dataset."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

import httpx

from config import OUTPUT_DIR

log = logging.getLogger(__name__)

_BATCH_SIZE = 20


def compute_chunks_hash(report_id: str) -> str:
    """Compute SHA256 hash for the pushable chunk set."""
    from utils.fastgpt_adapter import load_chunks_v3

    chunks = load_chunks_v3(report_id)
    if not chunks:
        raise FileNotFoundError(f"Chunks not found for report {report_id}")

    if "info" in chunks:
        normalized = [{
            "chunk_id": "info",
            "summary": chunks["info"].get("summary", ""),
            "content": chunks["info"].get("content", ""),
            "index_tags": chunks["info"].get("index_tags", []),
        }]
    else:
        normalized = []
        for chunk_id in sorted(chunks.keys()):
            if chunk_id in {"tracking", "chunk7"}:
                continue
            row = chunks[chunk_id]
            normalized.append({
                "chunk_id": chunk_id,
                "summary": row.get("summary", ""),
                "content": row.get("content", ""),
                "index_tags": row.get("index_tags", []),
            })
    content = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:16]


def _load_push_records(report_id: str) -> dict[str, Any]:
    from db import get_db

    meta_path = OUTPUT_DIR / f"{report_id}.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            push_records = meta.get("push_records")
            if isinstance(push_records, dict):
                return push_records
        except Exception as e:
            log.warning("Failed to read push records from %s: %s", meta_path, e)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT push_records FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if row and row["push_records"]:
            try:
                parsed = json.loads(row["push_records"])
                if isinstance(parsed, dict):
                    return parsed
            except Exception as e:
                log.warning("Failed to parse push_records for %s: %s", report_id, e)
        return {}
    finally:
        conn.close()


def _write_push_records(report_id: str, push_records: dict[str, Any]) -> None:
    from db import get_db

    meta_path = OUTPUT_DIR / f"{report_id}.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        meta["push_records"] = push_records
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    conn = get_db()
    try:
        conn.execute(
            "UPDATE reports SET push_records = ?, updated_at = ? WHERE report_id = ?",
            (json.dumps(push_records, ensure_ascii=False), datetime.now().isoformat(), report_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_push_record(report_id: str, dataset_id: str) -> dict[str, Any] | None:
    push_records = _load_push_records(report_id)
    record = push_records.get(dataset_id)
    return record if isinstance(record, dict) else None


def clear_push_record(report_id: str, dataset_id: str) -> None:
    push_records = _load_push_records(report_id)
    if dataset_id in push_records:
        push_records.pop(dataset_id, None)
        _write_push_records(report_id, push_records)
        log.info("Cleared push record for %s → dataset %s", report_id, dataset_id)


def save_push_record(
    report_id: str,
    dataset_id: str,
    collection_id: str,
    uploaded: int,
    total: int,
) -> None:
    chunks_hash = compute_chunks_hash(report_id)
    push_records = _load_push_records(report_id)
    push_records[dataset_id] = {
        "collection_id": collection_id,
        "pushed_at": datetime.now().isoformat(),
        "chunks_hash": chunks_hash,
        "uploaded": uploaded,
        "total": total,
    }
    _write_push_records(report_id, push_records)
    log.info("Saved push record for %s → dataset %s (hash=%s)", report_id, dataset_id, chunks_hash)


async def delete_collection(collection_id: str, fastgpt_config: dict[str, str]) -> None:
    """Delete a FastGPT collection. Failures are logged but not raised."""
    api_url = fastgpt_config.get("api_url", "").rstrip("/")
    api_key = fastgpt_config.get("api_key", "")
    headers = {
        "Authorization": api_key if api_key.startswith("Bearer ") else f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            res = await client.delete(
                f"{api_url}/collection/delete",
                headers=headers,
                params={"id": collection_id},
            )
            if res.status_code == 200:
                log.info("Deleted old FastGPT collection: %s", collection_id)
            else:
                log.warning("Failed to delete collection %s (%d): %s", collection_id, res.status_code, res.text)
    except Exception as e:
        log.warning("Error deleting collection %s: %s", collection_id, e)


async def push_chunks_to_fastgpt(
    chunks: list[dict[str, Any]],
    collection_name: str,
    fastgpt_config: dict[str, str],
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Push chunks to FastGPT knowledge base."""
    api_url = fastgpt_config.get("api_url", "").rstrip("/")
    api_key = fastgpt_config.get("api_key", "")
    dataset_id = fastgpt_config.get("dataset_id", "")

    if not all([api_url, api_key, dataset_id]):
        raise ValueError("FastGPT 配置不完整：需要 api_url、api_key 和 dataset_id")

    headers = {
        "Authorization": api_key if api_key.startswith("Bearer ") else f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(verify=False, timeout=60) as client:
        create_payload = {
            "datasetId": dataset_id,
            "name": collection_name,
            "type": "virtual",
        }
        if tags:
            create_payload["tags"] = tags

        res = await client.post(
            f"{api_url}/collection/create",
            headers=headers,
            json=create_payload,
        )
        if res.status_code != 200:
            raise RuntimeError(f"创建集合失败 ({res.status_code}): {res.text}")

        res_json = res.json()
        collection_id = res_json.get("data")
        if isinstance(collection_id, dict):
            collection_id = collection_id.get("_id") or collection_id.get("id")
        log.info("FastGPT collection created: %s (ID: %s)", collection_name, collection_id)

        total = len(chunks)
        uploaded = 0

        for i in range(0, total, _BATCH_SIZE):
            batch = chunks[i : i + _BATCH_SIZE]
            api_data = []
            for item in batch:
                indexes = item.get("indexes", [])
                if indexes and not isinstance(indexes[0], dict):
                    indexes = [{"text": str(idx)} for idx in indexes]
                api_data.append({
                    "q": item.get("q", ""),
                    "a": item.get("a", ""),
                    "indexes": indexes,
                })

            r = await client.post(
                f"{api_url}/data/pushData",
                headers=headers,
                json={
                    "collectionId": collection_id,
                    "trainingType": "chunk",
                    "data": api_data,
                },
            )
            if r.status_code == 200:
                uploaded += len(batch)
                log.info("FastGPT push progress: %d/%d", uploaded, total)
            else:
                log.error("FastGPT pushData failed: %s", r.text)
                raise RuntimeError(f"推送数据失败 ({r.status_code}): {r.text}")

    return {"collection_id": collection_id, "uploaded": uploaded, "total": total}


def _load_report_push_context(report_id: str) -> dict[str, Any]:
    from db import get_db

    company_name = "未知公司"
    bd_code = report_id[:8]
    push_records: dict[str, Any] = {}
    manual_rating = None
    rating = None
    feasibility_rating = None
    report_format = "v3"
    metadata_json: dict[str, Any] = {}

    meta_path = OUTPUT_DIR / f"{report_id}.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            company_name = meta.get("company_name", company_name)
            bd_code = meta.get("bd_code", bd_code)
            push_records = meta.get("push_records", {}) or {}
            manual_rating = meta.get("manual_rating")
            rating = meta.get("rating")
            feasibility_rating = meta.get("feasibility_rating")
            report_format = meta.get("report_format", report_format)
            metadata_json = meta.get("metadata_json", {}) or {}
        except Exception as e:
            log.warning("Failed to read report meta JSON for %s: %s", report_id, e)
    else:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT company_name, bd_code, rating, manual_rating, "
                "feasibility_rating, push_records, report_format, metadata_json "
                "FROM reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if row:
                company_name = row["company_name"] or company_name
                bd_code = row["bd_code"] or bd_code
                manual_rating = row["manual_rating"]
                rating = row["rating"]
                feasibility_rating = row["feasibility_rating"]
                report_format = row["report_format"] or report_format
                if row["push_records"]:
                    try:
                        push_records = json.loads(row["push_records"])
                    except Exception as e:
                        log.warning("Failed to parse DB push_records for %s: %s", report_id, e)
                if row["metadata_json"]:
                    try:
                        metadata_json = json.loads(row["metadata_json"])
                    except Exception:
                        metadata_json = {}
        finally:
            conn.close()

    return {
        "company_name": company_name,
        "bd_code": bd_code,
        "push_records": push_records if isinstance(push_records, dict) else {},
        "final_rating": manual_rating or rating,
        "feasibility_rating": feasibility_rating,
        "report_format": report_format,
        "metadata_json": metadata_json if isinstance(metadata_json, dict) else {},
    }


def build_fastgpt_payload(report_id: str) -> dict[str, Any]:
    from utils.fastgpt_adapter import (
        build_fastgpt_chunks_v3,
        build_fastgpt_chunks_v4,
        load_chunks_v3,
    )

    context = _load_report_push_context(report_id)
    chunks_dict = load_chunks_v3(report_id)

    report_format = context.get("report_format") or "v3"
    if "info" in chunks_dict:
        report_format = "v4"
    metadata_json = context.get("metadata_json") or {}

    if report_format == "v4" or "info" in chunks_dict:
        chunks = build_fastgpt_chunks_v4(
            report_id,
            chunks_dict,
            context["company_name"],
            context["bd_code"],
            info_summary=metadata_json.get("info_summary"),
            info_index_tags=metadata_json.get("info_index_tags") or [],
        )
    else:
        chunks = build_fastgpt_chunks_v3(
            report_id,
            chunks_dict,
            context["company_name"],
            context["bd_code"],
        )

    if not chunks:
        raise ValueError("No chunks to push")

    collection_name = f"{context['company_name']}-{context['bd_code']}"
    tags = ["尽调报告", context["bd_code"]]
    if report_format == "v4":
        tags.append("v4")
    if context["final_rating"]:
        tags.append(context["final_rating"])
    if context["feasibility_rating"]:
        tags.append(f"可行性{context['feasibility_rating']}")

    return {
        "report_format": report_format,
        "chunks": chunks,
        "collection_name": collection_name,
        "tags": tags,
        "context": context,
    }


async def push_report_to_fastgpt(
    report_id: str,
    fastgpt_config: dict[str, str],
    *,
    replace_existing: bool = True,
) -> dict[str, Any]:
    dataset_id = fastgpt_config.get("dataset_id", "")
    if not fastgpt_config.get("api_key"):
        raise ValueError("FastGPT API Key 未配置，请在设置页面配置")
    if not fastgpt_config.get("api_url"):
        raise ValueError("FastGPT API URL 未配置，请在设置页面配置")
    if not dataset_id:
        raise ValueError("FastGPT Dataset 未配置，请在设置页面配置")

    payload = build_fastgpt_payload(report_id)
    old_record = payload["context"]["push_records"].get(dataset_id)
    if replace_existing and old_record and old_record.get("collection_id"):
        await delete_collection(old_record["collection_id"], fastgpt_config)
        clear_push_record(report_id, dataset_id)

    result = await push_chunks_to_fastgpt(
        payload["chunks"],
        payload["collection_name"],
        fastgpt_config,
        tags=payload["tags"],
    )
    save_push_record(report_id, dataset_id, result["collection_id"], result["uploaded"], result["total"])
    result["push_record"] = {
        "dataset_id": dataset_id,
        "format": payload["report_format"],
        "collection_name": payload["collection_name"],
    }
    return result
