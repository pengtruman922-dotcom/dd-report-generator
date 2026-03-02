"""Step 1: Extractor Agent – parse Excel row + attachments into CompanyProfile JSON."""

from __future__ import annotations

import json
from typing import Any

from agents.base_agent import create_client, chat_completion
from prompts.extractor_prompt import SYSTEM_PROMPT


async def extract(
    excel_row: dict[str, Any],
    attachment_items: list[tuple[str, str]],
    ai_config: dict,
) -> tuple[dict[str, Any], dict]:
    """Run the extractor and return (CompanyProfile dict, usage_dict).

    attachment_items: list of (filename, text) tuples.

    Returns:
        tuple: (company_profile, usage_dict)
    """
    client = create_client(ai_config["base_url"], ai_config["api_key"])

    # Build user message
    parts: list[str] = []
    parts.append("## Excel行数据\n```json\n" + json.dumps(excel_row, ensure_ascii=False, indent=2) + "\n```")

    for i, (filename, text) in enumerate(attachment_items, 1):
        # Truncate very long attachments to 30k chars
        if len(text) > 30000:
            text = text[:30000] + "\n\n...[内容已截断]"
        parts.append(f"## 附件 {i}: {filename}\n{text}")

    user_message = "\n\n".join(parts)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    response, usage_dict = await chat_completion(client, ai_config["model"], messages)
    content = response.choices[0].message.content

    # Parse JSON from response (handle markdown code blocks)
    content = content.strip()
    if content.startswith("```"):
        # Remove ```json ... ```
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    return json.loads(content), usage_dict
