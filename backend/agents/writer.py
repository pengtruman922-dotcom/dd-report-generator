"""Step 3: Writer Agent – generate the full DD report in Markdown."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Callable

from agents.base_agent import create_client, chat_completion, chat_completion_stream
from prompts.writer_prompt import SYSTEM_PROMPT


async def write_report(
    company_profile: dict[str, Any],
    research_data: dict[str, Any],
    ai_config: dict,
    attachment_items: list[tuple[str, str]] | None = None,
    on_stream_chunk: Callable[[str], Any] | None = None,
    research_quality: str = "normal",  # "normal" | "insufficient"
) -> tuple[str, dict]:
    """Generate the full Markdown DD report. Returns (report text, usage_dict).

    attachment_items: optional list of (filename, text) tuples with raw attachment content.
    on_stream_chunk: optional callback for streaming chunks (async or sync function)

    Returns:
        tuple: (report_text, usage_dict)

    Note: When streaming, token usage is estimated based on content length since
    streaming responses don't always include usage information.
    """
    client = create_client(ai_config["base_url"], ai_config["api_key"])

    parts = [
        "请根据以下材料生成完整的尽调报告：\n",
        "## CompanyProfile（公司档案）\n```json\n"
        + json.dumps(company_profile, ensure_ascii=False, indent=2)
        + "\n```\n",
        "## ResearchData（网络研究数据）\n```json\n"
        + json.dumps(research_data, ensure_ascii=False, indent=2)
        + "\n```\n",
    ]

    # Inject data quality warning when research found nothing
    if research_quality == "insufficient":
        parts.append(
            "## ⚠️ 数据质量警告\n"
            "本次联网调研未能获取到该公司的有效公开信息（搜索结果为空或无法确认公司身份）。\n"
            "**撰写报告时必须严格遵守以下规则**：\n"
            "1. **禁止推断或编造任何未经信息来源支撑的数据**，包括财务数据、行业地位、竞争格局等\n"
            "2. **所有无来源的字段必须明确标注「信息缺失，待核实」**，不得用「未披露」「暂未获取」等模糊说法填充实质内容\n"
            "3. **报告的核心价值在于：准确识别信息缺口 + 给出具体的补充信息行动建议**\n"
            "4. 行业分析部分如无法确认公司所属行业，**不得撰写行业分析章节**\n"
            "5. 估值分析章节**必须省略**，因为无财务数据支撑\n"
            "6. 报告开头必须用醒目方式标注：「本报告因公开信息极度有限，主要内容为信息缺口梳理和尽调行动建议，不含实质性财务及经营分析」\n\n"
        )

    # Append raw attachment texts so the writer has full context
    if attachment_items:
        parts.append("## 原始附件材料\n以下是用户上传的附件原文，包含结构化提取可能遗漏的细节数据，请充分利用：\n")
        for i, (filename, text) in enumerate(attachment_items, 1):
            # Truncate per attachment to manage token budget
            truncated = text[:20000] + "\n\n...[内容已截断]" if len(text) > 20000 else text
            parts.append(f"### 附件 {i}: {filename}\n{truncated}\n")

    parts.append(f"今天的日期是：{date.today().isoformat()}\n")

    user_message = "\n".join(parts)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # Use streaming if callback is provided
    if on_stream_chunk:
        full_content = []
        async for chunk in chat_completion_stream(
            client,
            ai_config["model"],
            messages,
            temperature=0.4,
        ):
            full_content.append(chunk)
            # Call the callback (handle both sync and async)
            if asyncio.iscoroutinefunction(on_stream_chunk):
                await on_stream_chunk(chunk)
            else:
                on_stream_chunk(chunk)

        report_text = "".join(full_content)

        # Estimate token usage for streaming (rough approximation: 1 token ≈ 4 chars)
        # This is a fallback since streaming doesn't always provide usage info
        estimated_completion_tokens = len(report_text) // 4
        estimated_prompt_tokens = (len(user_message) + len(SYSTEM_PROMPT)) // 4
        usage_dict = {
            "prompt_tokens": estimated_prompt_tokens,
            "completion_tokens": estimated_completion_tokens,
            "total_tokens": estimated_prompt_tokens + estimated_completion_tokens,
        }

        return report_text, usage_dict
    else:
        # Non-streaming fallback
        response, usage_dict = await chat_completion(
            client,
            ai_config["model"],
            messages,
            temperature=0.4,
        )
        return response.choices[0].message.content, usage_dict
