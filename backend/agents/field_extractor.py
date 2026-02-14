"""Step 4: Field Extractor Agent – extract structured fields from the report to update metadata."""

from __future__ import annotations

import json
from typing import Any

from agents.base_agent import create_client, chat_completion
from prompts.field_extractor_prompt import SYSTEM_PROMPT


async def extract_fields(
    current_metadata: dict[str, Any],
    report_md: str,
    ai_config: dict,
) -> dict[str, Any]:
    """Extract structured fields from the generated report.

    Returns a dict of {field_key: new_value} for fields that should be updated.
    """
    client = create_client(ai_config["base_url"], ai_config["api_key"])

    # Truncate report if extremely long (to stay within token limits)
    if len(report_md) > 60000:
        report_md = report_md[:60000] + "\n\n...[内容已截断]"

    # Build user message with current metadata and the report
    user_message = (
        "## 当前已有录入数据\n```json\n"
        + json.dumps(current_metadata, ensure_ascii=False, indent=2)
        + "\n```\n\n"
        "## 尽调报告全文\n"
        + report_md
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    response = await chat_completion(
        client, ai_config["model"], messages, temperature=0.1
    )
    content = response.choices[0].message.content.strip()

    # Parse JSON from response (handle markdown code blocks)
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    result = json.loads(content)
    if not isinstance(result, dict):
        return {}
    return result
