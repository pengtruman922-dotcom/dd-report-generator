"""Base AI client wrapper using OpenAI-compatible API."""

from __future__ import annotations

from openai import AsyncOpenAI


def create_client(base_url: str, api_key: str) -> AsyncOpenAI:
    """Create an AsyncOpenAI client for the given endpoint."""
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


async def chat_completion(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
) -> dict:
    """Call chat completions and return the raw response dict."""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = await client.chat.completions.create(**kwargs)
    return response
