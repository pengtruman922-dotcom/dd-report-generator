"""Baidu search provider (via SerpAPI or Baidu custom search)."""

from __future__ import annotations

from typing import Any

import httpx

from tools.base import ToolProvider
from tools.registry import register

_SERPAPI_ENDPOINT = "https://serpapi.com/search"


@register
class BaiduSearch(ToolProvider):
    tool_type = "search"
    provider_id = "baidu"
    display_name = "百度搜索"
    description = "百度搜索（通过 SerpAPI），中国大陆可用"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "api_key",
                "label": "SerpAPI Key",
                "type": "password",
                "required": True,
                "default": "",
                "description": "SerpAPI 的 API Key（用于调用百度搜索）",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web using Baidu. Use this to find company information, "
                    "financial data, industry reports, news, legal filings, etc. "
                    "Best for Chinese content."
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

        params = {
            "engine": "baidu",
            "q": query,
            "num": max_results,
            "api_key": api_key,
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(_SERPAPI_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results[:max_results]
