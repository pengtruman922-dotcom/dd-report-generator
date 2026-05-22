"""v4 info chunk writer."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from prompts.info_chunk_prompt import INFO_CHUNK_PROMPT
from services.prompt_manager import get_prompt

log = logging.getLogger(__name__)


async def write_info_chunk(
    *,
    company_profile: dict[str, Any],
    material_summary: str,
    attachment_summaries: dict[str, str] | None,
    research_data: dict[str, Any] | None,
    seller_fact_snapshot: dict[str, Any] | None,
    existing_info_chunk: dict[str, Any] | None,
    ai_config: dict[str, Any],
) -> dict[str, Any]:
    """Generate the v4 info chunk."""
    client = AsyncOpenAI(
        base_url=ai_config.get("base_url", ""),
        api_key=ai_config.get("api_key", ""),
    )
    model = ai_config.get("model", "qwen3-max")

    user_payload = {
        "company_profile": company_profile,
        "material_summary": (material_summary or "").strip(),
        "attachment_summaries": attachment_summaries or {},
        "research_data": research_data or {},
        "seller_fact_snapshot": seller_fact_snapshot or {},
        "existing_info_chunk": existing_info_chunk or {},
    }

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": get_prompt("info_chunk", INFO_CHUNK_PROMPT),
            },
            {
                "role": "user",
                "content": (
                    "请根据以下输入生成 v4 的 info_chunk：\n\n"
                    f"```json\n{json.dumps(user_payload, ensure_ascii=False, indent=2)}\n```"
                ),
            },
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        lines = [line for line in content.splitlines() if not line.strip().startswith("```")]
        content = "\n".join(lines)

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise
        result = json.loads(match.group(0))

    result.setdefault("summary", "")
    result.setdefault("content", "")
    result.setdefault("extracted_fields", {})
    result.setdefault("index_tags", [])
    return result
