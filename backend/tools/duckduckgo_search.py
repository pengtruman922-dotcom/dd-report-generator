"""DuckDuckGo search provider (free, no API key required)."""

from __future__ import annotations

import asyncio
from typing import Any

from duckduckgo_search import DDGS

from tools.base import ToolProvider
from tools.registry import register


@register
class DuckDuckGoSearch(ToolProvider):
    tool_type = "search"
    provider_id = "duckduckgo"
    display_name = "DuckDuckGo"
    description = "免费搜索引擎，无需API Key（中国大陆可能不可用）"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "region",
                "label": "搜索区域",
                "type": "text",
                "required": False,
                "default": "wt-wt",  # 全球搜索
                "description": "搜索区域代码，如 wt-wt (全球), us-en (美国), cn-zh (中国)",
            },
            {
                "key": "proxy",
                "label": "代理地址",
                "type": "text",
                "required": False,
                "default": "",
                "description": "HTTP代理地址，如 http://127.0.0.1:7890（可选）",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web using DuckDuckGo. Use this to find company information, "
                    "financial data, industry reports, news, legal filings, etc. "
                    "Supports Chinese queries well (region=cn-zh)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query string.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default 8, max 20).",
                            "default": 8,
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        query = args["query"]
        max_results = args.get("max_results", 8)
        region = self.config.get("region", "wt-wt")  # 默认全球搜索
        proxy = self.config.get("proxy", "")  # 可选代理
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._search(query, max_results, region, proxy),
        )

    @staticmethod
    def _search(query: str, max_results: int, region: str, proxy: str = "") -> list[dict]:
        results = []
        ddgs_kwargs = {}
        if proxy:
            ddgs_kwargs["proxy"] = proxy

        with DDGS(**ddgs_kwargs) as ddgs:
            for r in ddgs.text(query, region=region, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return results
