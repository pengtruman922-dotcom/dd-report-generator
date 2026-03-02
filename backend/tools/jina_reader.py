"""Jina Reader scraper provider — fetch web page as clean Markdown."""

from __future__ import annotations

from typing import Any

import httpx

from tools.base import ToolProvider
from tools.registry import register
from config import JINA_CONTENT_LIMIT

_JINA_PREFIX = "https://r.jina.ai/"


@register
class JinaReader(ToolProvider):
    tool_type = "scraper"
    provider_id = "jina_reader"
    display_name = "Jina Reader"
    description = "Jina AI 网页抓取服务，免费无需API Key（中国大陆可能不可用）"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "content_limit",
                "label": "内容截断长度",
                "type": "number",
                "required": False,
                "default": JINA_CONTENT_LIMIT,
                "description": "返回内容最大字符数",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "fetch_webpage",
                "description": (
                    "Fetch a web page and return its content as clean Markdown text. "
                    "Use this to read full articles, company profiles, financial reports, etc. "
                    "Content is truncated to ~8000 characters."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The full URL of the web page to fetch.",
                        },
                    },
                    "required": ["url"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        url = args["url"]
        limit = int(self.config.get("content_limit", JINA_CONTENT_LIMIT))
        jina_url = f"{_JINA_PREFIX}{url}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(jina_url, headers={"Accept": "text/markdown"})
            resp.raise_for_status()
            text = resp.text
        if len(text) > limit:
            text = text[:limit] + "\n\n...[内容已截断]"
        return text
