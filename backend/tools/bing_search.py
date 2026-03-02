"""Bing China search provider (requires API key)."""

from __future__ import annotations

from typing import Any

import httpx

from tools.base import ToolProvider
from tools.registry import register

_DEFAULT_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"


@register
class BingChinaSearch(ToolProvider):
    tool_type = "search"
    provider_id = "bing_china"
    display_name = "Bing 搜索（中国）"
    description = "微软 Bing 搜索 API，中国大陆可用，需要 API Key"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "api_key",
                "label": "API Key",
                "type": "password",
                "required": True,
                "default": "",
                "description": "Bing Search API 订阅密钥",
            },
            {
                "key": "endpoint",
                "label": "Endpoint",
                "type": "text",
                "required": False,
                "default": _DEFAULT_ENDPOINT,
                "description": "API 端点（一般无需修改）",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web using Bing. Use this to find company information, "
                    "financial data, industry reports, news, legal filings, etc. "
                    "Optimised for Chinese content (mkt=zh-CN)."
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
        api_key = self.config.get("api_key", "")
        endpoint = self.config.get("endpoint", _DEFAULT_ENDPOINT)

        headers = {"Ocp-Apim-Subscription-Key": api_key}
        params = {"q": query, "mkt": "zh-CN", "count": max_results}

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(endpoint, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
            })
        return results
