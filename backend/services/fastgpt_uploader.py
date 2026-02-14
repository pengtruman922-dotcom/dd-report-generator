"""FastGPT knowledge base uploader — push chunks to FastGPT dataset."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from config import OUTPUT_DIR

log = logging.getLogger(__name__)

# Batch size for pushData API calls
_BATCH_SIZE = 20


def compute_chunks_hash(report_id: str) -> str:
    """Compute SHA256 hash (first 16 hex chars) of the _chunks.json file."""
    chunks_path = OUTPUT_DIR / f"{report_id}_chunks.json"
    content = chunks_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


def save_push_record(
    report_id: str,
    dataset_id: str,
    collection_id: str,
    uploaded: int,
    total: int,
) -> None:
    """Save a push record into the report metadata JSON."""
    chunks_hash = compute_chunks_hash(report_id)
    meta_path = OUTPUT_DIR / f"{report_id}.json"
    meta: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    push_records = meta.get("push_records", {})
    push_records[dataset_id] = {
        "collection_id": collection_id,
        "pushed_at": datetime.now().isoformat(),
        "chunks_hash": chunks_hash,
        "uploaded": uploaded,
        "total": total,
    }
    meta["push_records"] = push_records
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
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
) -> dict[str, Any]:
    """Push chunks to FastGPT knowledge base.

    Args:
        chunks: List of {title, q, indexes: [{text}]} dicts
        collection_name: Name for the new collection in FastGPT
        fastgpt_config: {api_url, api_key, dataset_id}

    Returns:
        {"collection_id": str, "uploaded": int, "total": int}
    """
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
        # 1. Create collection
        res = await client.post(
            f"{api_url}/collection/create",
            headers=headers,
            json={
                "datasetId": dataset_id,
                "name": collection_name,
                "type": "virtual",
            },
        )
        if res.status_code != 200:
            raise RuntimeError(f"创建集合失败 ({res.status_code}): {res.text}")

        res_json = res.json()
        collection_id = res_json.get("data")
        if isinstance(collection_id, dict):
            collection_id = collection_id.get("_id") or collection_id.get("id")
        log.info("FastGPT collection created: %s (ID: %s)", collection_name, collection_id)

        # 2. Push data in batches
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
