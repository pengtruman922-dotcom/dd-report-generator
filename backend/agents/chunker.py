"""Chunker Agent — generates search indexes for report chunks via AI."""

from __future__ import annotations

import json
import logging
from typing import Any

from agents.base_agent import create_client, chat_completion
from prompts.chunker_prompt import SYSTEM_PROMPT

log = logging.getLogger(__name__)


async def generate_chunk_indexes(
    chunks: list[dict[str, Any]],
    metadata: dict[str, Any],
    ai_config: dict,
) -> list[list[dict[str, str]]]:
    """Generate indexes for all chunks in a single AI call.

    Returns a list of index arrays, one per chunk.
    Each index array contains dicts like {"text": "标签"}.
    """
    client = create_client(ai_config["base_url"], ai_config["api_key"])

    # Build context from metadata
    meta_context_parts = []
    if metadata.get("company_name"):
        meta_context_parts.append(f"公司全称: {metadata['company_name']}")
    if metadata.get("industry"):
        meta_context_parts.append(f"行业: {metadata['industry']}")
    if metadata.get("province"):
        loc = metadata["province"]
        if metadata.get("city"):
            loc += metadata["city"]
        meta_context_parts.append(f"所在地: {loc}")
    if metadata.get("is_listed"):
        meta_context_parts.append(f"上市状态: {metadata['is_listed']}")
    if metadata.get("stock_code"):
        meta_context_parts.append(f"证券代码: {metadata['stock_code']}")
    if metadata.get("revenue"):
        meta_context_parts.append(f"营收: {metadata['revenue']}")
    if metadata.get("net_profit"):
        meta_context_parts.append(f"净利润: {metadata['net_profit']}")
    if metadata.get("score") is not None:
        meta_context_parts.append(f"综合评分: {metadata['score']}")
    if metadata.get("rating"):
        meta_context_parts.append(f"评级: {metadata['rating']}")

    meta_context = "\n".join(meta_context_parts)

    # Build user message with all chunks
    chunk_descriptions = []
    for i, chunk in enumerate(chunks):
        # Truncate q field if very long to stay within token limits
        q_content = chunk["q"]
        if len(q_content) > 8000:
            q_content = q_content[:8000] + "\n...[内容已截断]"
        chunk_descriptions.append(
            f"### Chunk {i + 1}: {chunk['title']}\n\n{q_content}"
        )

    user_message = (
        f"## 公司元数据\n{meta_context}\n\n"
        f"## 报告分块内容（共{len(chunks)}个chunks）\n\n"
        + "\n\n---\n\n".join(chunk_descriptions)
        + "\n\n请为以上每个chunk生成15-22个搜索索引标签。"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    response = await chat_completion(
        client, ai_config["model"], messages, temperature=0.2
    )
    content = response.choices[0].message.content.strip()

    # Parse JSON from response (handle markdown code blocks)
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    result = json.loads(content)

    if not isinstance(result, list) or len(result) != len(chunks):
        log.warning(
            "AI returned %d index groups for %d chunks, adjusting",
            len(result) if isinstance(result, list) else 0,
            len(chunks),
        )
        if not isinstance(result, list):
            return [[] for _ in chunks]
        # Pad or trim to match chunk count
        while len(result) < len(chunks):
            result.append([])
        result = result[: len(chunks)]

    # Ensure each element is a list of {text: str} dicts
    validated = []
    for group in result:
        if isinstance(group, list):
            validated.append([
                item if isinstance(item, dict) and "text" in item
                else {"text": str(item)}
                for item in group
            ])
        else:
            validated.append([])

    return validated
