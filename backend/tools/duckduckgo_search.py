"""DuckDuckGo web search tool (free, no API key required)."""

from __future__ import annotations

from duckduckgo_search import DDGS


def web_search(query: str, max_results: int = 8, region: str = "cn-zh") -> list[dict]:
    """Search DuckDuckGo and return a list of result dicts.

    Each result has keys: title, href, body.
    """
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, region=region, max_results=max_results):
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
            )
    return results
