"""RatingAgent - Feasibility rating (A-E) for M&A projects."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from prompts.rating_agent_prompt import RATING_AGENT_SYSTEM_PROMPT
from services.prompt_manager import get_prompt

log = logging.getLogger(__name__)


def should_rate_on_create(user_inputs: dict) -> tuple[bool, str]:
    """判断新建标的时是否需要 AI 评级。

    Returns:
        (should_rate, reason)
    """
    import re

    text = user_inputs.get("text", "")

    # 检测用户输入是否包含明确评级
    rating_pattern = r'(?:评级|分级|评为|定为|调整为)\s*[:：]?\s*[A-Ea-e]'
    if re.search(rating_pattern, text):
        return False, "user_provided"

    return True, "no_user_rating"


def should_rate_on_update(
    user_inputs: dict, current_rating: dict | None, updated_chunks: list[str]
) -> tuple[bool, str]:
    """判断更新标的时是否需要重新评级。

    Returns:
        (should_rate, reason)
    """
    import re

    text = user_inputs.get("text", "")

    # 规则1：用户输入包含明确评级
    rating_pattern = r'(?:评级|分级|评为|定为|调整为|维持)\s*[:：]?\s*[A-Ea-e]'
    if re.search(rating_pattern, text):
        return False, "user_provided"

    # 规则2：tracking / chunk7（跟进动态）有更新
    if "tracking" in updated_chunks or "chunk7" in updated_chunks:
        return True, "tracking_updated"

    # 规则3：info / chunk0 / chunk5 有更新
    if "info" in updated_chunks or "chunk0" in updated_chunks or "chunk5" in updated_chunks:
        return True, "key_chunk_updated"

    # 规则4：其他 chunk 更新不触发评级
    return False, "non_rating_relevant"


def validate_rating_change(
    current_rating: dict | None, new_rating: dict, dimensions: dict
) -> tuple[bool, str]:
    """代码层校验评级变更的合理性。

    Returns:
        (accepted, reason)
    """
    if current_rating is None:
        return True, "initial_rating"

    old = current_rating.get("rating")
    new = new_rating.get("rating")

    if old == new:
        return True, "no_change"

    # 规则：变更为 E 级需要特别强的证据
    if new == "E":
        # 检查是否有明确的终止信号
        status_level = dimensions.get("status", {}).get("level", "")
        willingness_level = dimensions.get("willingness", {}).get("level", "")

        if status_level == "终止":
            return True, "status_terminated"
        if willingness_level == "消极" and "明确拒绝" in dimensions.get("willingness", {}).get("evidence", ""):
            return True, "explicitly_rejected"

        # 否则标记为需要用户确认
        return False, "downgrade_to_e_needs_confirmation"

    # 其他变更接受，但会进入 pending 状态等待用户确认
    return True, "rating_changed"


async def run_rating_agent(
    chunks: dict[str, dict],
    current_rating: dict | None,
    action: str,
    client: AsyncOpenAI,
    model: str,
) -> dict[str, Any]:
    """Run RatingAgent to generate feasibility rating.

    Args:
        chunks: {chunk_id: {summary, content, ...}}
        current_rating: 当前评级（更新时）{"rating": "B", "dimensions": {...}, "reasoning": "..."}
        action: "create" or "update"
        client: OpenAI client
        model: Model name

    Returns:
        {
            "rating": "A"~"E",
            "dimensions": {
                "willingness": {"level": "明确", "evidence": "..."},
                "cooperation": {"level": "未知", "evidence": "..."},
                "conditions": {"level": "基本成熟", "evidence": "..."},
                "status": {"level": "初步接触", "evidence": "..."}
            },
            "reasoning": "综合判断逻辑（2-3句话）",
            "key_factors": ["因素1", "因素2", "因素3"],
            "change_validated": true/false,  # 代码层校验结果
            "validation_reason": "..."
        }
    """
    # 组装评级输入
    rating_input_parts = []

    tracking_chunk = chunks.get("tracking") or chunks.get("chunk7") or {}
    info_chunk = chunks.get("info") or {}

    # 核心输入1：tracking 跟进动态（完整原文）
    if tracking_chunk.get("content"):
        rating_input_parts.append("## 跟进动态（完整原文）\n\n")
        rating_input_parts.append(tracking_chunk["content"])
        rating_input_parts.append("\n\n")

    # 核心输入2：info 摘要；兼容旧 chunk0 身份卡摘要
    if info_chunk.get("summary"):
        rating_input_parts.append("## 标的信息（摘要）\n\n")
        rating_input_parts.append(info_chunk["summary"])
        rating_input_parts.append("\n\n")
    elif "chunk0" in chunks and chunks["chunk0"].get("summary"):
        rating_input_parts.append("## 公司身份卡（摘要）\n\n")
        rating_input_parts.append(chunks["chunk0"]["summary"])
        rating_input_parts.append("\n\n")

    # 核心输入3：chunk1 财务数据摘要
    if "chunk1" in chunks and chunks["chunk1"].get("summary"):
        rating_input_parts.append("## 财务数据（摘要）\n\n")
        rating_input_parts.append(chunks["chunk1"]["summary"])
        rating_input_parts.append("\n\n")

    # 辅助输入：chunk5 交易条件摘要
    if "chunk5" in chunks and chunks["chunk5"].get("summary"):
        rating_input_parts.append("## 交易条件（摘要）\n\n")
        rating_input_parts.append(chunks["chunk5"]["summary"])
        rating_input_parts.append("\n\n")

    # 辅助输入：chunk4 风险摘要
    if "chunk4" in chunks and chunks["chunk4"].get("summary"):
        rating_input_parts.append("## 风险与合规（摘要）\n\n")
        rating_input_parts.append(chunks["chunk4"]["summary"])
        rating_input_parts.append("\n\n")

    # 更新场景：传入当前评级
    if action == "update" and current_rating:
        rating_input_parts.append("## 当前评级\n\n```json\n")
        rating_input_parts.append(json.dumps(current_rating, ensure_ascii=False, indent=2))
        rating_input_parts.append("\n```\n\n")
        rating_input_parts.append(
            "注意：这是更新场景，除非有明确证据表明评级应该变更，否则应保持稳定。"
            "特别是变更为 E 级，必须有明确的终止信号或拒绝证据。\n\n"
        )

    rating_input = "".join(rating_input_parts)

    messages = [
        {"role": "system", "content": get_prompt("rating_agent", RATING_AGENT_SYSTEM_PROMPT)},
        {"role": "user", "content": rating_input},
    ]

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
        )

        content = response.choices[0].message.content or ""
        content = content.strip()

        # 解析 JSON
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        rating_result = json.loads(content)

        # 代码层校验
        validated, reason = validate_rating_change(
            current_rating, rating_result, rating_result.get("dimensions", {})
        )

        rating_result["change_validated"] = validated
        rating_result["validation_reason"] = reason

        return rating_result

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse rating JSON: {e}")
        # 降级：返回保守评级
        return {
            "rating": "C",
            "dimensions": {
                "willingness": {"level": "未知", "evidence": "解析失败"},
                "cooperation": {"level": "未知", "evidence": "解析失败"},
                "conditions": {"level": "未知", "evidence": "解析失败"},
                "status": {"level": "未知", "evidence": "解析失败"},
            },
            "reasoning": "评级解析失败，给予保守评级 C",
            "key_factors": ["评级解析失败"],
            "change_validated": True,
            "validation_reason": "fallback_rating",
        }
    except Exception as e:
        log.error(f"RatingAgent failed: {e}")
        raise
