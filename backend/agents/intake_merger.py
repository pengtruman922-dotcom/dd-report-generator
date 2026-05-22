"""Merge IntakeAgent and MatcherAgent results into final confirmation data."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def merge_intake_and_matcher(
    intake_result: dict,
    matcher_result: dict,
) -> list[dict[str, Any]]:
    """Merge IntakeAgent and MatcherAgent results.

    Args:
        intake_result: {
            "targets": [
                {"project_name": "好当家", "material_summary": "...", "related_attachments": [...]},
                ...
            ]
        }
        matcher_result: {
            "matches": [
                {"project_name": "好当家", "action": "update", "matched_report_id": "rpt_xxx", "confidence": "high", "reason": "..."},
                ...
            ]
        }

    Returns:
        [
            {
                "project_name": "好当家",
                "action": "update",
                "matched_report_id": "rpt_xxx",
                "matched_company_name": "好当家集团股份有限公司",
                "match_confidence": "high",
                "match_reason": "...",
                "material_summary": "...",
                "related_attachments": ["file1.pdf", "file2.docx"]
            },
            ...
        ]
    """
    intake_targets = intake_result.get("targets", [])
    matcher_matches = matcher_result.get("matches", [])

    # 构建 project_name → match 的映射
    match_map = {}
    for match in matcher_matches:
        project_name = match.get("project_name", "")
        match_map[project_name] = match

    # 合并
    merged = []
    for target in intake_targets:
        project_name = target.get("project_name", "")
        match = match_map.get(project_name, {})

        merged_item = {
            "project_name": project_name,
            "bd_code": target.get("bd_code"),
            "action": match.get("action", "create"),
            "matched_report_id": match.get("matched_report_id"),
            "matched_company_name": match.get("matched_company_name"),
            "match_confidence": match.get("confidence"),
            "match_reason": match.get("reason"),
            "material_summary": target.get("material_summary", ""),
            "tracking_material_summary": target.get("tracking_material_summary", ""),
            "related_attachments": target.get("related_attachments", []),
        }

        merged.append(merged_item)

    return merged


def validate_confirmation_data(merged_data: list[dict]) -> list[dict]:
    """Validate and clean confirmation data.

    - 确保必需字段存在
    - 清理空值
    - 标记需要用户注意的项（confidence 为 medium/low）
    """
    validated = []

    for item in merged_data:
        # 必需字段
        if not item.get("project_name"):
            log.warning("Skipping item without project_name: %s", item)
            continue

        # 标记需要用户注意
        confidence = item.get("match_confidence")
        if confidence in ("medium", "low"):
            item["needs_user_attention"] = True
            item["attention_reason"] = f"匹配置信度为 {confidence}，请确认是否正确"
        else:
            item["needs_user_attention"] = False

        # action 默认为 create
        if not item.get("action"):
            item["action"] = "create"

        validated.append(item)

    return validated
