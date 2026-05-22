#!/usr/bin/env python
"""Push local JSON data to a FastGPT dataset.

This script is intentionally standalone: it does not import the project backend
and only uses Python standard library modules.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BATCH_SIZE = 20


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, indent=2)


def _normalize_indexes(value: Any) -> list[dict[str, str]]:
    if not value:
        return []

    raw_items = value if isinstance(value, list) else [value]
    result: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in raw_items:
        if isinstance(item, dict):
            text = _as_text(item.get("text") or item.get("name") or item.get("value"))
        else:
            text = _as_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append({"text": text})

    return result


def _normalize_item(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"q": item.strip(), "a": "", "indexes": []}

    if not isinstance(item, dict):
        return {"q": _as_text(item), "a": "", "indexes": []}

    q = _as_text(
        item.get("q")
        or item.get("content")
        or item.get("text")
        or item.get("markdown")
        or item.get("body")
        or item
    )
    a = _as_text(item.get("a") or item.get("answer") or "")

    indexes = _normalize_indexes(item.get("indexes"))
    if not indexes:
        index_values: list[Any] = []
        for key in ("index_tags", "tags", "keywords"):
            value = item.get(key)
            if isinstance(value, list):
                index_values.extend(value)
            elif value:
                index_values.append(value)
        if item.get("summary"):
            index_values.append(item["summary"])
        indexes = _normalize_indexes(index_values)

    return {"q": q, "a": a, "indexes": indexes}


def normalize_input(data: Any) -> list[dict[str, Any]]:
    """Accept common JSON shapes and convert them to FastGPT pushData rows."""
    if isinstance(data, dict):
        for key in ("data", "chunks", "items", "documents"):
            if isinstance(data.get(key), list):
                return [_normalize_item(item) for item in data[key]]
        return [_normalize_item(data)]

    if isinstance(data, list):
        return [_normalize_item(item) for item in data]

    return [_normalize_item(data)]


def _request_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    *,
    insecure: bool = False,
) -> dict[str, Any]:
    headers = {
        "Authorization": api_key if api_key.startswith("Bearer ") else f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=body, headers=headers, method=method)
    context = ssl._create_unverified_context() if insecure else None

    try:
        with urlopen(req, timeout=60, context=context) as res:
            text = res.read().decode("utf-8")
            return json.loads(text) if text else {}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed ({e.code}): {detail}") from e
    except URLError as e:
        raise RuntimeError(f"{method} {url} failed: {e}") from e


def create_collection(
    api_url: str,
    api_key: str,
    dataset_id: str,
    name: str,
    tags: list[str],
    *,
    insecure: bool,
) -> str:
    payload: dict[str, Any] = {
        "datasetId": dataset_id,
        "name": name,
        "type": "virtual",
    }
    if tags:
        payload["tags"] = tags

    res = _request_json(
        "POST",
        f"{api_url.rstrip('/')}/collection/create",
        api_key,
        payload,
        insecure=insecure,
    )
    collection_id = res.get("data")
    if isinstance(collection_id, dict):
        collection_id = collection_id.get("_id") or collection_id.get("id")
    if not collection_id:
        raise RuntimeError(f"FastGPT did not return collection id: {res}")
    return str(collection_id)


def push_data(
    api_url: str,
    api_key: str,
    collection_id: str,
    rows: list[dict[str, Any]],
    *,
    batch_size: int,
    insecure: bool,
) -> int:
    uploaded = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        payload = {
            "collectionId": collection_id,
            "trainingType": "chunk",
            "data": batch,
        }
        _request_json(
            "POST",
            f"{api_url.rstrip('/')}/data/pushData",
            api_key,
            payload,
            insecure=insecure,
        )
        uploaded += len(batch)
        print(f"pushed {uploaded}/{len(rows)}")
    return uploaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Push JSON rows to FastGPT dataset.")
    parser.add_argument("input", help="JSON file path")
    parser.add_argument("--api-url", default=os.getenv("FASTGPT_API_URL", ""), help="FastGPT API base URL")
    parser.add_argument("--api-key", default=os.getenv("FASTGPT_API_KEY", ""), help="FastGPT API key")
    parser.add_argument("--dataset-id", default=os.getenv("FASTGPT_DATASET_ID", ""), help="FastGPT dataset id")
    parser.add_argument("--collection-name", default="", help="New collection name")
    parser.add_argument("--collection-id", default="", help="Push into an existing collection instead of creating one")
    parser.add_argument("--tag", action="append", default=[], help="Collection tag; can be repeated")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    parser.add_argument("--dry-run", action="store_true", help="Only print normalized FastGPT payload")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    data = _read_json(input_path)
    rows = [row for row in normalize_input(data) if row.get("q")]

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    missing = [
        name
        for name, value in {
            "--api-url or FASTGPT_API_URL": args.api_url,
            "--api-key or FASTGPT_API_KEY": args.api_key,
        }.items()
        if not value
    ]
    if not args.collection_id and not args.dataset_id:
        missing.append("--dataset-id or FASTGPT_DATASET_ID")
    if missing:
        print("Missing required config: " + ", ".join(missing), file=sys.stderr)
        return 2

    collection_id = args.collection_id
    if not collection_id:
        collection_name = args.collection_name or input_path.stem
        collection_id = create_collection(
            args.api_url,
            args.api_key,
            args.dataset_id,
            collection_name,
            args.tag,
            insecure=args.insecure,
        )
        print(f"created collection: {collection_name} ({collection_id})")

    uploaded = push_data(
        args.api_url,
        args.api_key,
        collection_id,
        rows,
        batch_size=max(1, args.batch_size),
        insecure=args.insecure,
    )
    print(json.dumps({"collection_id": collection_id, "uploaded": uploaded, "total": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
