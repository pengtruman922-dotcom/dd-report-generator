"""Utility helpers for v4 summary and index generation."""

from __future__ import annotations

import re
from typing import Any


def _fallback_summary(text: str, limit: int = 180) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit]


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        text = str(tag or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


_SEARCH_KEYWORDS = [
    "数据中心", "节能服务", "综合能源", "合同能源管理", "EPC", "储能", "液冷",
    "机器人", "传感器", "编码器", "光栅尺", "关节模组", "智能制造", "国产替代",
    "食品", "番茄", "农产品深加工", "出口", "消费品牌", "供应链",
    "医疗器械", "医药", "新能源", "锂电", "半导体", "汽车零部件", "纺织", "环保",
    "上市公司", "非上市", "新三板", "港股IPO", "美股上市", "IPO", "控制权转让",
    "股权转让", "出售意向", "估值", "报价", "未审计", "专精特新", "高新技术企业",
]


def _extract_search_tags(text: str) -> list[str]:
    """Derive short retrieval tags from chunk text without adding subjective labels."""
    if not text:
        return []

    tags: list[str] = []
    for keyword in _SEARCH_KEYWORDS:
        if keyword in text:
            tags.append(keyword)

    stock_match = re.search(r"(?:证券代码|股票代码)[:：\s]*([0-9]{6})", text)
    if stock_match:
        tags.append(stock_match.group(1))

    for province in re.findall(r"(北京|上海|天津|重庆|广东|江苏|浙江|山东|安徽|福建|湖北|湖南|四川|河南|河北|江西|陕西|辽宁|新疆|内蒙古|广西|海南|云南|贵州|山西|吉林|黑龙江)", text):
        tags.append(province)

    return tags[:20]


def build_index_bundle(
    *,
    company_name: str,
    bd_code: str,
    info_chunk: dict[str, Any] | None,
    tracking_chunk: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build normalized summary/index metadata for v4 chunks."""
    info_chunk = info_chunk or {}
    tracking_chunk = tracking_chunk or {}

    info_summary = (info_chunk.get("summary") or "").strip()
    if not info_summary:
        info_summary = _fallback_summary(info_chunk.get("content", ""))

    tracking_summary = (tracking_chunk.get("summary") or "").strip()
    if not tracking_summary:
        tracking_summary = _fallback_summary(tracking_chunk.get("content", ""), limit=120)

    info_content = info_chunk.get("content", "") or ""
    info_tags = info_chunk.get("index_tags", []) or []
    base_tags = [company_name, bd_code]
    generated_tags = _extract_search_tags(info_content)
    info_index_tags = _dedupe_tags([*base_tags, *[str(tag) for tag in info_tags], *generated_tags])

    return {
        "info_summary": info_summary,
        "info_index_tags": info_index_tags,
        "tracking_summary": tracking_summary,
    }
