"""Jina Reader – fetch web page as clean Markdown (free, no API key)."""

from __future__ import annotations

import httpx

from config import JINA_CONTENT_LIMIT

JINA_PREFIX = "https://r.jina.ai/"


async def fetch_webpage(url: str) -> str:
    """Fetch *url* via Jina Reader and return Markdown text (truncated)."""
    jina_url = f"{JINA_PREFIX}{url}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(jina_url, headers={"Accept": "text/markdown"})
        resp.raise_for_status()
        text = resp.text
    # Truncate to control token usage
    if len(text) > JINA_CONTENT_LIMIT:
        text = text[:JINA_CONTENT_LIMIT] + "\n\n...[内容已截断]"
    return text
