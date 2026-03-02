"""巨潮资讯网 provider — query listed company announcements."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from tools.base import ToolProvider
from tools.registry import register

log = logging.getLogger(__name__)

_CNINFO_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
_CATEGORY_MAP = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "季报": "category_jibg_szsh",
}


@register
class CninfoProvider(ToolProvider):
    tool_type = "datasource"
    provider_id = "cninfo"
    display_name = "巨潮资讯网"
    description = "查询上市公司公告（年报、半年报、季报等），无需API Key"
    target_company_type = "listed"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return []  # No config needed — public API

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "cninfo_search",
                "description": (
                    "Search announcements of Chinese listed companies on cninfo.com.cn. "
                    "Use this to find annual reports, semi-annual reports, quarterly reports, "
                    "and other public filings."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stock_code": {
                            "type": "string",
                            "description": "Stock code, e.g. '000001' or '600519'.",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "Optional keyword to filter announcements.",
                        },
                        "category": {
                            "type": "string",
                            "description": "Report category: 年报, 半年报, 季报 (optional).",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results to return (default 5).",
                            "default": 5,
                        },
                    },
                    "required": ["stock_code"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        stock_code = args["stock_code"]
        keyword = args.get("keyword", "")
        category = args.get("category", "")
        max_results = args.get("max_results", 5)

        category_code = _CATEGORY_MAP.get(category, "")

        form_data = {
            "pageNum": 1,
            "pageSize": max_results,
            "column": "szse" if stock_code.startswith(("0", "3")) else "sse",
            "tabName": "fulltext",
            "plate": "",
            "stock": stock_code,
            "searchkey": keyword,
            "secid": "",
            "category": category_code,
            "trade": "",
            "seDate": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_CNINFO_URL, data=form_data, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        announcements = data.get("announcements") or []
        results = []
        for ann in announcements[:max_results]:
            adj_url = ann.get("adjunctUrl", "")
            full_url = f"http://static.cninfo.com.cn/{adj_url}" if adj_url else ""
            results.append({
                "title": ann.get("announcementTitle", "").replace("<em>", "").replace("</em>", ""),
                "url": full_url,
                "date": ann.get("announcementTime", ""),
                "type": ann.get("announcementTypeName", ""),
            })
        return results
