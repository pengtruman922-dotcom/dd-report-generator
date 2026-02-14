"""OpenAI-compatible function-calling tool definitions for the Researcher agent."""

TOOLS = [
    {
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
                        "description": "The search query string. Use Chinese for Chinese companies.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 8, max 20).",
                        "default": 8,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
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
    },
]
