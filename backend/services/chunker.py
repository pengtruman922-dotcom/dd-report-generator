"""Core chunking + AI indexing logic for splitting reports into RAG-ready chunks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Chinese numeral section headers used in the report
_SECTION_NUMS = [
    "一", "二", "三", "四", "五", "六", "七", "八",
    "九", "十", "十一", "十二", "十三",
]

# Chunk merge rules: (title_suffix, list of section numbers to merge)
_CHUNK_RULES = [
    ("核心摘要", ["一", "十三"]),
    ("基本信息与股权结构", ["二", "三", "四"]),
    ("主营业务分析", ["五", "六", "八"]),
    ("财务状况分析", ["七"]),
    ("风险评估与估值分析", ["九", "十", "十一", "十二"]),
]

# Common suffixes to strip when deriving short name (longest first)
_STRIP_SUFFIXES = [
    "集团股份有限公司", "科技股份有限公司", "股份有限公司",
    "科技有限责任公司", "有限责任公司", "集团有限公司",
    "科技有限公司", "生物科技有限公司", "有限公司",
]

# Province/city prefixes to strip from short names
_LOCATION_PREFIXES = [
    "广东省", "江苏省", "浙江省", "山东省", "四川省", "湖北省", "湖南省",
    "辽宁省", "福建省", "安徽省", "河南省", "河北省",
    "广东", "江苏", "浙江", "山东", "四川", "湖北", "湖南",
    "辽宁", "福建", "安徽", "河南", "河北",
    "深圳市", "广州市", "苏州市", "杭州市", "南京市", "佛山市", "无锡市",
    "深圳", "广州", "苏州", "杭州", "南京", "佛山", "无锡",
    "北京", "上海", "天津", "重庆",
]

# Industry keywords to strip from the tail of short names
# NOTE: avoid short/common words like "电子","生物" that appear in core names (微电子, 生物谷)
_INDUSTRY_SUFFIXES = [
    "半导体材料", "智能科技", "智能装备", "智能健康", "新材料",
    "生物科技", "环保科技", "节能科技", "精密科技", "医疗科技",
    "科技发展", "科技", "医疗",
]


def _derive_short_name(company_name: str) -> str:
    """Derive a short name from full company name by stripping suffixes, prefixes, and noise."""
    name = company_name

    # Strip English parts (e.g. "基汇资本Gaw Capital Partners" -> "基汇资本")
    # Find where Chinese text ends and English begins
    for i, ch in enumerate(name):
        if ch.isascii() and ch.isalpha():
            candidate = name[:i].strip()
            if len(candidate) >= 2:
                name = candidate
            break

    # Strip common company suffixes
    for suffix in sorted(_STRIP_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    # Strip parenthetical location markers like （苏州）、（上海）
    name = re.sub(r"[（(][^）)]{1,4}[）)]", "", name)

    # Strip location prefixes if result is still meaningful (>= 3 chars)
    for prefix in sorted(_LOCATION_PREFIXES, key=len, reverse=True):
        if name.startswith(prefix) and len(name) - len(prefix) >= 3:
            name = name[len(prefix):]
            break

    # Strip trailing industry keywords if result is still meaningful
    for suffix in sorted(_INDUSTRY_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix) and len(name) - len(suffix) >= 2:
            name = name[: -len(suffix)]
            break

    return name.strip() if name.strip() else company_name


def _parse_sections(report_md: str) -> dict[str, str]:
    """Parse markdown by ## headings into a dict keyed by Chinese numeral section number."""
    sections: dict[str, str] = {}
    # Split on ## headings, capturing the heading text
    parts = re.split(r"(?=^## )", report_md, flags=re.MULTILINE)

    for part in parts:
        if not part.strip():
            continue
        # Match section heading like "## 一、执行摘要" or "## 十三、结论与建议"
        m = re.match(r"^## \s*([\u4e00-\u9fff]+)[、，,.]\s*", part)
        if m:
            section_num = m.group(1)
            if section_num in _SECTION_NUMS:
                sections[section_num] = part.strip()
            continue
        # Also try matching "## 附录" etc. — skip these
        if part.startswith("## "):
            heading = part.split("\n", 1)[0].strip()
            if "附录" in heading:
                continue
            # For non-standard headings, try to detect section number
            for num in _SECTION_NUMS:
                if num in heading[:10]:
                    sections[num] = part.strip()
                    break

    return sections


def split_report_to_chunks(
    report_md: str,
    company_name: str,
    short_name: str,
    listing_status: str,
) -> list[dict[str, Any]]:
    """Split a report markdown into 5 chunks with empty indexes.

    Returns list of dicts with {title, q, indexes: []}.
    """
    sections = _parse_sections(report_md)

    if not sections:
        log.warning("No sections found in report, falling back to single chunk")
        header = f"【企业名称】{company_name}\n【上市状态】{listing_status}\n\n"
        return [{
            "title": f"{short_name}-完整报告",
            "q": header + report_md,
            "indexes": [],
        }]

    chunks = []
    header = f"【企业名称】{company_name}\n【上市状态】{listing_status}\n\n"

    for title_suffix, section_nums in _CHUNK_RULES:
        merged_parts = []
        for num in section_nums:
            if num in sections:
                merged_parts.append(sections[num])

        if not merged_parts:
            # Still create the chunk with header only for consistency
            merged_content = ""
        else:
            # Join with double newline; strip trailing --- from each part
            cleaned = []
            for p in merged_parts:
                p = p.rstrip()
                if p.endswith("---"):
                    p = p[:-3].rstrip()
                cleaned.append(p)
            merged_content = "\n\n".join(cleaned)

        chunks.append({
            "title": f"{short_name}-{title_suffix}",
            "q": header + merged_content,
            "indexes": [],
        })

    return chunks


async def generate_indexes(
    chunks: list[dict[str, Any]],
    company_name: str,
    metadata: dict[str, Any],
    ai_config: dict,
) -> list[dict[str, Any]]:
    """Generate AI indexes for all chunks via a single AI call.

    Returns the chunks with indexes populated.
    """
    from agents.chunker import generate_chunk_indexes

    indexes_list = await generate_chunk_indexes(chunks, metadata, ai_config)

    # Merge indexes into chunks
    result = []
    for i, chunk in enumerate(chunks):
        chunk_copy = {**chunk}
        if i < len(indexes_list):
            chunk_copy["indexes"] = indexes_list[i]
        result.append(chunk_copy)

    return result


def chunk_and_index_sync(
    report_md: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """Synchronous chunking only (no AI indexes). Used as fallback."""
    company_name = metadata.get("company_name", "未知公司")
    short_name = _derive_short_name(company_name)
    listing_status = metadata.get("is_listed") or "未知"
    return split_report_to_chunks(report_md, company_name, short_name, listing_status)


async def chunk_and_index(
    report_md: str,
    metadata: dict[str, Any],
    ai_config: dict,
) -> list[dict[str, Any]]:
    """Orchestrator: split report into chunks, then generate AI indexes.

    Returns list of chunks with {title, q, indexes: [{text: ...}]}.
    """
    company_name = metadata.get("company_name", "未知公司")
    short_name = _derive_short_name(company_name)
    listing_status = metadata.get("is_listed") or "未知"

    # Step 1: Rule-based chunking
    chunks = split_report_to_chunks(report_md, company_name, short_name, listing_status)

    # Step 2: AI index generation
    if ai_config.get("api_key"):
        try:
            chunks = await generate_indexes(chunks, company_name, metadata, ai_config)
        except Exception as e:
            log.exception("AI index generation failed, returning chunks without indexes: %s", e)

    return chunks
