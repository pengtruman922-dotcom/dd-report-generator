"""Bocha Web Search provider (China mainland, API key required).

Bocha is a semantic search engine designed for AI applications.
Official endpoint: https://api.bochaai.com/v1/web-search
Register at https://open.bochaai.com to obtain an API key.
"""

from __future__ import annotations

from typing import Any

import httpx

from tools.base import ToolProvider
from tools.registry import register

_DEFAULT_ENDPOINT = "https://api.bochaai.com/v1/web-search"


@register
class BochaSearch(ToolProvider):
    tool_type = "search"
    provider_id = "bocha"
    display_name = "博查搜索"
    description = (
        "博查 AI 搜索 API，国内直连无需翻墙，"
        "DeepSeek 官方联网搜索供应方，语义排序对 LLM 友好"
    )

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "api_key",
                "label": "API Key",
                "type": "password",
                "required": True,
                "default": "",
                "description": "博查开放平台 API Key（open.bochaai.com 获取）",
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
                    "Search the web using Bocha, a Chinese AI search engine with "
                    "semantic ranking. Use this to find company information, "
                    "financial data, industry reports, news, legal filings, etc. "
                    "Optimised for Chinese content."
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
                            "description": "Number of results (default 10, max 50).",
                            "default": 10,
                        },
                        "freshness": {
                            "type": "string",
                            "description": (
                                "Time range filter. Values: 'noLimit', 'oneDay', "
                                "'oneWeek', 'oneMonth', 'oneYear', or "
                                "'YYYY-MM-DD..YYYY-MM-DD'. Default: 'noLimit'."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        query = args["query"]
        max_results = min(args.get("max_results", 10), 50)
        freshness = args.get("freshness", "noLimit")
        api_key = self.config.get("api_key", "")
        endpoint = self.config.get("endpoint", _DEFAULT_ENDPOINT)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "freshness": freshness,
            "count": max_results,
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("data", {}).get("webPages", {}).get("value", []):
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "siteName": item.get("siteName", ""),
                "datePublished": item.get("datePublished", ""),
            })
        return results
