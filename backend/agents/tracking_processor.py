"""v4 tracking processor."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from prompts.tracking_processor_prompt import TRACKING_PROCESSOR_PROMPT
from services.prompt_manager import get_prompt

log = logging.getLogger(__name__)


async def process_tracking(
    *,
    company_profile: dict[str, Any],
    material_summary: str,
    attachment_summaries: dict[str, str] | None,
    existing_tracking_chunk: dict[str, Any] | None,
    existing_snapshot: dict[str, Any] | None,
    ai_config: dict[str, Any],
    current_system_time: str | None = None,
) -> dict[str, Any]:
    """Generate tracking chunk plus seller snapshot for v4."""
    client = AsyncOpenAI(
        base_url=ai_config.get("base_url", ""),
        api_key=ai_config.get("api_key", ""),
    )
    model = ai_config.get("model", "qwen3-max")

    user_payload = {
        "company_profile": company_profile,
        "current_system_time": current_system_time,
        "material_summary": (material_summary or "").strip(),
        "attachment_summaries": attachment_summaries or {},
        "existing_tracking_chunk": existing_tracking_chunk or {},
        "existing_snapshot": existing_snapshot or {},
    }

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": get_prompt(
                    "tracking_processor",
                    TRACKING_PROCESSOR_PROMPT,
                ),
            },
            {
                "role": "user",
                "content": (
                    "请根据以下输入生成 tracking_chunk、seller_fact_snapshot 和 excluded_context：\n\n"
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

    tracking_chunk = result.get("tracking_chunk") or {}
    extracted_fields = result.get("extracted_fields") or {}
    snapshot = result.get("seller_fact_snapshot") or {}

    tracking_chunk.setdefault("summary", "")
    tracking_chunk.setdefault("content", "")
    tracking_chunk.setdefault("index_tags", [])
    extracted_fields.setdefault("referral_status", "暂无跟进记录")
    extracted_fields.setdefault("is_traded", snapshot.get("transaction_status"))

    return {
        "tracking_chunk": tracking_chunk,
        "seller_fact_snapshot": snapshot,
        "excluded_context": result.get("excluded_context") or [],
        "extracted_fields": extracted_fields,
    }
