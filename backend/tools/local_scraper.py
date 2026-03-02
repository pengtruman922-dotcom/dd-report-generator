"""Local web scraper provider — httpx + readability-lxml, no external service."""

from __future__ import annotations

import re
from typing import Any

import httpx

from tools.base import ToolProvider
from tools.registry import register

_DEFAULT_TIMEOUT = 30
_DEFAULT_CONTENT_LIMIT = 8000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text. Uses readability-lxml if available, else regex."""
    try:
        from readability import Document
        doc = Document(html)
        content_html = doc.summary()
        # Strip remaining HTML tags
        text = re.sub(r"<[^>]+>", "", content_html)
        text = re.sub(r"\s+", " ", text).strip()
        # Restore some structure
        text = text.replace(". ", ".\n")
        return text
    except ImportError:
        # Fallback: simple tag stripping
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text


@register
class LocalScraper(ToolProvider):
    tool_type = "scraper"
    provider_id = "local_scraper"
    display_name = "本地抓取器"
    description = "使用 httpx 本地抓取网页，无需外部服务，中国大陆可用"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "timeout",
                "label": "超时时间(秒)",
                "type": "number",
                "required": False,
                "default": _DEFAULT_TIMEOUT,
                "description": "HTTP 请求超时时间",
            },
            {
                "key": "content_limit",
                "label": "内容截断长度",
                "type": "number",
                "required": False,
                "default": _DEFAULT_CONTENT_LIMIT,
                "description": "返回内容最大字符数",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "fetch_webpage",
                "description": (
                    "Fetch a web page and return its content as plain text. "
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
        timeout = int(self.config.get("timeout", _DEFAULT_TIMEOUT))
        limit = int(self.config.get("content_limit", _DEFAULT_CONTENT_LIMIT))

        headers = {"User-Agent": _USER_AGENT}
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, verify=True
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text

        text = _html_to_text(html)
        if len(text) > limit:
            text = text[:limit] + "\n\n...[内容已截断]"
        return text
