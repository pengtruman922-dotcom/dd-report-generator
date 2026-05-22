"""Build WriterAgent input for each target."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def build_writer_agent_input(
    confirmation_item: dict,
    existing_report: dict | None,
    existing_chunks: dict | None,
) -> dict[str, Any]:
    """Build input for WriterAgent based on confirmation data.

    Args:
        confirmation_item: {
            "project_name": "好当家",
            "action": "create" | "update",
            "matched_report_id": "rpt_xxx" | None,
            "matched_company_name": "好当家集团股份有限公司" | None,
            "material_summary": "...",
            "related_attachments": ["file1.pdf", "file2.docx"]
        }
        existing_report: 已有报告的元数据（更新时）
        existing_chunks: 已有 chunks（更新时）{chunk_id: {summary, content}}

    Returns:
        {
            "action": "create" | "update",
            "company_profile": {
                "company_name": "...",
                "industry": "...",
                "stock_code": "...",
                "is_listed": "是" | "否",
                ...
            },
            "material_summary": "...",
            "attachment_filenames": ["file1.pdf", "file2.docx"],
            "existing_chunks": {...} | None
        }
    """
    action = confirmation_item.get("action", "create")
    project_name = confirmation_item.get("project_name", "")
    material_summary = confirmation_item.get("material_summary", "")
    related_attachments = confirmation_item.get("related_attachments", [])

    # 构建 company_profile
    if action == "update" and existing_report:
        # 更新模式：从已有报告中提取
        company_profile = {
            "company_name": existing_report.get("company_name", project_name),
            "project_name": existing_report.get("project_name", project_name),
            "industry": existing_report.get("industry"),
            "stock_code": existing_report.get("stock_code"),
            "is_listed": existing_report.get("is_listed"),
            "province": existing_report.get("province"),
            "city": existing_report.get("city"),
            "district": existing_report.get("district"),
        }
    else:
        # 新建模式：只有项目名称
        company_profile = {
            "company_name": project_name,
            "project_name": project_name,
        }

    return {
        "action": action,
        "company_profile": company_profile,
        "material_summary": material_summary,
        "attachment_filenames": related_attachments,
        "existing_chunks": existing_chunks if action == "update" else None,
    }


def build_company_profile_from_chunks(chunks: dict) -> dict:
    """Extract company profile from chunks (for update scenarios).

    Args:
        chunks: {chunk_id: {summary, content, extracted_fields}}

    Returns:
        company_profile dict
    """
    profile = {}

    # 从 chunk0 提取
    if "chunk0" in chunks:
        fields = chunks["chunk0"].get("extracted_fields", {})
        profile.update({
            "company_name": fields.get("company_name"),
            "project_name": fields.get("project_name"),
            "is_listed": fields.get("is_listed"),
            "stock_code": fields.get("stock_code"),
            "province": fields.get("province"),
            "city": fields.get("city"),
            "district": fields.get("district"),
        })

    # 从 chunk3 提取行业
    if "chunk3" in chunks:
        fields = chunks["chunk3"].get("extracted_fields", {})
        if fields.get("industry"):
            profile["industry"] = fields["industry"]

    return profile
