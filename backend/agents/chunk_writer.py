"""Chunk writer - writes individual chunks for v3.0 reports."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from prompts.chunk_prompts import get_chunk_prompt

log = logging.getLogger(__name__)


async def write_chunk(
    chunk_id: str,
    instruction: str,
    shared_context: dict[str, Any],
    existing_content: str | None,
    client: AsyncOpenAI,
    model: str,
) -> dict[str, Any]:
    """Write or update a single chunk.

    Args:
        chunk_id: chunk0~chunk7
        instruction: WriterAgent 给出的写作指令
        shared_context: 共享上下文（调研数据、附件摘要等）
        existing_content: 更新模式下的现有内容
        client: OpenAI client
        model: Model name

    Returns:
        {
            "summary": "chunk 摘要（100-200字）",
            "content": "chunk 正文内容",
            "extracted_fields": {...},  # 该 chunk 对应的结构化字段
            "index_tags": ["标签1", "标签2"]  # 向量检索标签
        }
    """
    system_prompt = get_chunk_prompt(chunk_id)

    # 构建用户消息
    user_parts = []

    # 1. 写作指令
    user_parts.append(f"## 写作指令\n\n{instruction}")

    # 2. 共享上下文
    if shared_context:
        user_parts.append("\n## 共享上下文\n")
        if shared_context.get("research_data"):
            user_parts.append("### 调研数据\n```json\n")
            user_parts.append(json.dumps(shared_context["research_data"], ensure_ascii=False, indent=2))
            user_parts.append("\n```\n")
        if shared_context.get("attachment_summaries"):
            user_parts.append("\n### 附件摘要\n")
            for filename, summary in shared_context["attachment_summaries"].items():
                user_parts.append(f"**{filename}**:\n{summary}\n\n")
        if shared_context.get("company_profile"):
            user_parts.append("\n### 公司基本信息\n```json\n")
            user_parts.append(json.dumps(shared_context["company_profile"], ensure_ascii=False, indent=2))
            user_parts.append("\n```\n")

    # 3. 更新模式：注入现有内容
    if existing_content:
        user_parts.append(f"\n## 现有内容（增量更新）\n\n{existing_content}\n")
        user_parts.append("\n请在现有内容基础上进行增量修改，保留未受影响的部分。")

    user_message = "".join(user_parts)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""
        content = content.strip()

        # 解析 JSON 输出
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            # 尝试更宽松的解析：用正则提取 JSON 大括号内容
            log.warning(f"Chunk {chunk_id} strict JSON parse failed: {e}, trying fallback")
            import re
            m = re.search(r'\{[\s\S]*\}', content)
            if m:
                try:
                    result = json.loads(m.group(0))
                except json.JSONDecodeError:
                    raise e
            else:
                raise e

        # 确保必需字段存在
        if "summary" not in result:
            result["summary"] = ""
        if "content" not in result:
            result["content"] = ""
        if "extracted_fields" not in result:
            result["extracted_fields"] = {}
        if "index_tags" not in result:
            result["index_tags"] = []

        return result

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse chunk {chunk_id} JSON output: {e}")
        # 降级：返回原始内容
        return {
            "summary": "",
            "content": content,
            "extracted_fields": {},
            "index_tags": [],
        }
    except Exception as e:
        log.error(f"Failed to write chunk {chunk_id}: {e}")
        raise
